"""Read-only discovery of potential distressed acquisition notices in Illinois RSS.

No login, PACER document downloads, bidding, contacting sellers, or trading.
Docket announcements are leads only; court orders determine actual terms.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import html
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

FEEDS = {
    "ILNB": "https://ecf.ilnb.uscourts.gov/cgi-bin/rss_outside.pl",
    "ILCB": "https://ecf.ilcb.uscourts.gov/cgi-bin/rss_outside.pl",
    "ILSB": "https://ecf.ilsb.uscourts.gov/cgi-bin/rss_outside.pl",
}
UA = "DistressedAcquisitionScout/0.1 (research; public RSS metadata only)"
MAX_FEED_BYTES = 6_000_000
SALE = re.compile(
    r"\b(?:363\s*(?:\(|sale|motion)|sell\s+(?:substantially\s+all|assets|business)|"
    r"(?:sale|sell|auction)\s+of\s+(?:assets|business)|bidding\s+procedures|"
    r"sale\s+motion|stalking\s+horse|assum(?:e|ption)\s+and\s+assign(?:ment)?|"
    r"executory\s+contracts|asset\s+purchase\s+agreement)\b", re.I)
EXCLUDE = re.compile(
    r"\b(?:sheriff'?s?\s+sale|foreclosure\s+sale|tax\s+sale|"
    r"341\s+meeting|proof\s+of\s+claim|vehicle\s+auction)\b", re.I)
KEYS = ("contract", "receivable", "customer", "subscription", "software", "licens", "asset", "business")

def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()

def _tag(e: ET.Element, name: str) -> str:
    for x in e:
        if x.tag.rsplit("}", 1)[-1] == name:
            return (x.text or "").strip()
    return ""

def _date(s: str) -> str | None:
    if not s:
        return None
    try:
        return email.utils.parsedate_to_datetime(s).astimezone(dt.timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None

def parse_feed(body: bytes, court: str, source_url: str) -> list[dict]:
    if len(body) > MAX_FEED_BYTES:
        raise ValueError("RSS exceeds byte limit")
    root = ET.fromstring(body)
    items = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "item"]
    leads: list[dict] = []
    for item in items:
        title = _plain(_tag(item, "title"))
        description = _plain(_tag(item, "description"))
        combined = f"{title} {description}"
        if not SALE.search(combined) or EXCLUDE.search(combined):
            continue
        link = _tag(item, "link")
        # Do not automatically open docket links: some incur PACER document fees.
        leads.append({
            "court": court,
            "title": title,
            "description_excerpt": description[:850],
            "published_utc": _date(_tag(item, "pubDate")),
            "docket_link_unopened": link if link.startswith("https://") else None,
            "free_source_url": source_url,
            "keywords": [k for k in KEYS if k in combined.lower()],
            "status": "UNVERIFIED_DOCKET_LEAD",
            "bid_deadline": None,
            "minimum_bid_usd": None,
            "deposit_usd": None,
            "contracts_assignable": None,
            "verified_cash_flow_usd": None,
            "financing_committed": False,
        })
    return leads

def fetch_public_feed(url: str, *, opener=urllib.request.urlopen) -> bytes:
    if url not in FEEDS.values():
        raise ValueError("Only allowlisted free court RSS URLs may be requested")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml"})
    with opener(request, timeout=20) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_FEED_BYTES:
            raise ValueError("RSS exceeds byte limit")
        body = response.read(MAX_FEED_BYTES + 1)
    if len(body) > MAX_FEED_BYTES:
        raise ValueError("RSS exceeds byte limit")
    return body

def scan(feeds: dict[str, str] | None = None) -> dict:
    urls = feeds or FEEDS
    leads: list[dict] = []
    errors: dict[str, str] = {}
    for court, url in urls.items():
        try:
            leads.extend(parse_feed(fetch_public_feed(url), court, url))
        except (ValueError, ET.ParseError, urllib.error.URLError, OSError) as err:
            errors[court] = f"{type(err).__name__}: {str(err)[:180]}"
    seen: set[tuple[str, str, str]] = set()
    distinct: list[dict] = []
    for item in leads:
        key = (item["court"], item["title"], item.get("docket_link_unopened") or "")
        if key not in seen:
            distinct.append(item)
            seen.add(key)
    distinct.sort(key=lambda x: (x["published_utc"] or "", len(x["keywords"])), reverse=True)
    return {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "purpose": "DISCOVERY_ONLY_NOT_AN_AVAILABLE_OR_FINANCEABLE_DEAL",
        "pacer_requests": 0,
        "fees_incurred_usd": 0,
        "courts_checked": list(urls),
        "courts_failed": errors,
        "potential_docket_leads": len(distinct),
        "verified_live_financeable_deals": 0,
        "candidates": distinct,
        "next_step": "Manually obtain FREE sale notice and validate bid deadline, price, deposit, contracts and financing before calling a deal actionable.",
    }

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default="output/acquisitions/illinois-latest.json")
    opts = p.parse_args(argv)
    report = scan()
    dest = Path(opts.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "pacer_requests", "courts_failed", "potential_docket_leads",
        "verified_live_financeable_deals")}, sort_keys=True))
    return 0 if not report["courts_failed"] else 2

if __name__ == "__main__":
    sys.exit(main())
