"""Discover free public Chapter 11, Article 9 and distressed-asset sale notices.

Only retrieve explicitly allowlisted RSS endpoints. Do not visit article links,
fee-bearing docket URLs, login pages or download documents automatically.
"""
from __future__ import annotations

import calendar
import datetime as dt
import html
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

NOTICE_FEEDS = {
    "DAILYDAC_PUBLIC_NOTICES":
        "https://www.dailydac.com/category/premium-public-notices/feed/",
    "DAILYDAC_NLR_PUBLIC_NOTICES":
        "https://www.dailydac.com/category/premium-public-notices/nlr_and_dd/feed/",
}
MAX_BYTES = 3_000_000
MAX_ITEMS_PER_FEED = 80
USER_AGENT = "AcquisitionScout/0.2 (public-RSS-research; no credentials)"
NOTICE_WORDS = re.compile(
    r"\b(?:bankruptcy|chapter\s+11|363\s+sale|article\s+9|ucc|"
    r"sale\s+process|asset\s+sale|notice\s+of\s+auction|"
    r"foreclosure\s+of\s+business\s+assets|receivership)\b", re.I)
CONTRACT_WORDS = ("contract", "receivable", "customer", "software", "subscription", "licens", "purchase order")
MONTHS = "|".join(calendar.month_name[1:] + calendar.month_abbr[1:])
DATES = re.compile(r"\b((?:" + MONTHS +
    r")\.?\s+\d{1,2},?\s+20\d{2}|\d{1,2}/\d{1,2}/20\d{2})\b", re.I)
DEADLINE_LABELS = re.compile(
    r"\b(?:bid deadline|deadline for qualified bids(?: and deposits)?|"
    r"bids? due|bid submission deadline|deadline for bids)\b", re.I)

def strip_markup(value: str) -> str:
    value = re.sub(r"(?is)<(?:style|script)[^>]*>.*?</(?:style|script)>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"(?s)<[^>]+>", " ", value))).strip()

def node_text(node: ET.Element, tag: str) -> str:
    for c in node:
        if c.tag.rsplit("}", 1)[-1].lower() == tag.lower():
            return (c.text or "").strip()
    return ""

def published_date(raw: str) -> str | None:
    import email.utils
    try:
        value = email.utils.parsedate_to_datetime(raw)
        if value.tzinfo is None:
            return None
        return value.astimezone(dt.timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None

def parse_date(raw: str) -> dt.date | None:
    raw = raw.replace(".", "").replace(",", "").strip()
    for fmt in ("%B %d %Y", "%b %d %Y", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    return None

def deadline_from_text(text: str) -> tuple[str | None, str | None]:
    # Dates are extracted from explicit *bid deadline* sentences, not guessed
    # from auction, hearing or article publication dates.
    for match in DEADLINE_LABELS.finditer(text):
        context = text[match.end():match.end()+145]
        found = DATES.search(context)
        if found:
            date = parse_date(found.group(1))
            if date:
                return date.isoformat(), context[:110].strip()
    return None, None

def parse_notice_feed(body: bytes, source: str, feed_url: str,
                      *, today: dt.date | None = None) -> list[dict]:
    if len(body) > MAX_BYTES:
        raise ValueError("Public feed exceeds byte limit")
    today = today or dt.datetime.now(dt.timezone.utc).date()
    root = ET.fromstring(body)
    notices: list[dict] = []
    items = [x for x in root.iter() if x.tag.rsplit("}", 1)[-1] == "item"]
    for item in items[:MAX_ITEMS_PER_FEED]:
        title = strip_markup(node_text(item, "title"))
        text = strip_markup(" ".join((node_text(item, "description"),
                                      node_text(item, "encoded"))))
        combined = title + " " + text
        if not NOTICE_WORDS.search(combined):
            continue
        link = node_text(item, "link")
        # Link included only as reference for future manual review, never fetched.
        if not link.startswith("https://www.dailydac.com/"):
            continue
        kind = (
            "PROSPECTIVE_CHAPTER_11" if "prospective chapter 11" in combined.lower()
            else "CHAPTER_11" if re.search(r"chapter\s*11|363\s*sale", combined, re.I)
            else "ARTICLE_9" if re.search(r"article\s*9|ucc", combined, re.I)
            else "OTHER_DISTRESSED"
        )
        deadline, context = deadline_from_text(combined)
        state = (
            "PROSPECTIVE_NOT_FILED" if kind == "PROSPECTIVE_CHAPTER_11"
            else "BID_DATE_PAST_AS_PUBLISHED" if deadline and dt.date.fromisoformat(deadline) < today
            else "FUTURE_DATE_REQUIRES_FRESH_VERIFICATION" if deadline and dt.date.fromisoformat(deadline) >= today
            else "NO_VERIFIED_BID_DEADLINE"
        )
        notices.append({
            "source": source,
            "source_type": "FREE_PUBLIC_NOTICE_RSS",
            "title": title,
            "url": link,
            "published_utc": published_date(node_text(item, "pubDate")),
            "notice_type": kind,
            "bid_deadline_as_published": deadline,
            "deadline_context_excerpt": context,
            "status": state,
            "description_excerpt": text[:650],
            "contract_related_mentions": [s for s in CONTRACT_WORDS if s in combined.lower()],
            "purchase_price_usd": None,
            "required_deposit_usd": None,
            "contracts_assignable": None,
            "verified_cashflow_usd": None,
            "funding_committed": False,
            "verified_actionable": False,
        })
    return notices

class _NoCrossDomainRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlsplit
        parts = urlsplit(newurl)
        if parts.scheme != "https" or parts.hostname not in ("www.dailydac.com", "dailydac.com"):
            raise ValueError("Redirect off allowlisted free notice domain blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def get_free_notice_rss(url: str, *, opener=None) -> bytes:
    if url not in NOTICE_FEEDS.values():
        raise ValueError("URL not in explicit public-notice feed allowlist")
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"})
    opener = opener or urllib.request.build_opener(_NoCrossDomainRedirect()).open
    with opener(request, timeout=16) as resp:
        count = resp.headers.get("Content-Length")
        if count and int(count) > MAX_BYTES:
            raise ValueError("Public feed exceeds byte limit")
        data = resp.read(MAX_BYTES+1)
    if len(data) > MAX_BYTES:
        raise ValueError("Public feed exceeds byte limit")
    return data

def scan_notice_sources(*, today: dt.date | None = None) -> dict:
    results: list[dict] = []
    errors: dict[str, str] = {}
    for source, url in NOTICE_FEEDS.items():
        try:
            results += parse_notice_feed(get_free_notice_rss(url), source, url, today=today)
        except (ValueError, ET.ParseError, urllib.error.URLError, OSError) as err:
            errors[source] = type(err).__name__ + ": " + str(err)[:200]
    dedup: dict[str, dict] = {}
    for item in results:
        key = item["url"].rstrip("/").lower()
        if key not in dedup:
            dedup[key] = item
        elif item["description_excerpt"] and len(item["description_excerpt"]) > len(dedup[key]["description_excerpt"]):
            dedup[key] = item
    records = list(dedup.values())
    records.sort(key=lambda i: (i["status"] == "FUTURE_DATE_REQUIRES_FRESH_VERIFICATION",
                                i.get("published_utc") or ""), reverse=True)
    return {
        "sources_checked": NOTICE_FEEDS,
        "source_errors": errors,
        "free_sale_notice_matches": len(records),
        "notice_candidates": records,
        "future_bid_dates_unconfirmed": sum(
            x["status"] == "FUTURE_DATE_REQUIRES_FRESH_VERIFICATION" for x in records),
        "verified_actionable_deals": 0,
        "notes": [
            "All extracted deadlines are as published, not validated against latest court orders.",
            "Unknown acquisition prices, contract transfer rights, cash flow and financing remain null.",
            "Only allowlisted free public RSS was requested; article links and PACER never opened."
        ],
    }
