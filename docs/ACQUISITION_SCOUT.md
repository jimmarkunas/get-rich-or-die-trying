# Distressed Acquisition Scout — Illinois free-source read-only gate

**Not an acquisition recommendation or proof of financeable contracts.**

Input: public bankruptcy docket metadata via official RSS feeds from Northern, Central and Southern Districts of Illinois. Northern District says feed updates hourly and covers preceding 24 hours. Docket announcements are not full filings.

## Commands

python -m acquisitions.scout --out output/acquisitions/illinois-latest.json

python -m unittest discover -s tests -p 'test_acquisition_scout.py' -v

GitHub Actions is manual or PR-only, **not scheduled**. Runs read-only and uploads evidence even on a court feed error. No login, paid PACER, credentials, automated bids, outreach or trades.

## Gate before marking an opportunity actionable

1. Identify debtor, case number, sale counsel/trustee and public filing source.
2. Obtain a free sale notice/approved motion, verify live deadline, price, deposits and bidder qualification. **Do not automatically open RSS docket links; some incur PACER fees.**
3. Inspect assets and proposed Section 365 contracts for actual assignability.
4. Attorney reviews consent, cure and adequate assurance; independently verify historic receipts, collection rights, fulfillment cost and working capital.
5. Obtain debt/equity commitment before any bid. Unperformed contracts are not automatically financeable invoices.

All financial fields default to null and leads remain UNVERIFIED_DOCKET_LEAD; verified live financeable deal count remains zero until human due diligence. This scanner does not produce valuations, proof of financing or contract-transfer rights.

No new scheduled ChatGPT task. LIFE OS and existing trading jobs unchanged.


## Expanded public sources (October 2026)

The pipeline command is now:
  python -m acquisitions.pipeline --out output/acquisitions/illinois-latest.json

The existing court-only command remains available. The new pipeline also checks public Chapter 11 / Section 363, UCC Article 9, and pre-filing sales in two allowlisted DailyDAC public-notice RSS feeds. Public auction notices are *discovery leads*, not automatically available or financeable contracts. The RSS content is never trusted for current court-approved dates. No article or document links are automatically followed.

Free case-agent reference directories:
- Epiq public case index: https://dm.epiq11.com/
- Kroll public case index: https://www.kroll.com/en/restructuring-administration-cases

Those case-agent directories are recorded for manual cross-reference only, because their live case search/document interfaces have not passed source ingestion tests. Their documents are not counted as automatically covered.

Each RSS item preserves a primary free URL, relevant contract words, a date **only when identified as a bid deadline**, and separate status (deadline unknown, expired as published, future as published but unconfirmed, or prospective case not filed). All prices, deposits, contract assignment rights and verified cash flow remain null without independent primary-source evidence. A pending deadline is NOT a qualified bid or an acquisition.

### Real examples to research, not purchase recommendations

- UPG Enterprises, LLC, Northern District of Illinois case 26-15734. Published bidding motion proposed October 28, 2026 bid deadline; November 2 auction. Three proposed stalking-horse bids aggregate over $14M plus inventory. Proposed 10% bid deposit and financial-capability requirements. Too capital intensive to bid directly with under $1,000. Public case portal: https://dm.epiq11.com/ and free public summary: https://app.bondoro.com/preview/cases/Upg_Enterprises_LLC/apa-summary . Check entered court order before action.
- Prospective upper-Midwest foundry, October 5 DailyDAC notice; contemplated Chapter 11 only, not a pending approved sale, net losses reported, $7M estimated pension withdrawal exposure before a sale. Public notice: https://www.dailydac.com/public-notice-of-prospective-chapter-11-filing-and-363-sale-process-aluminum-brass-bronze-foundry-and-machine-shop/ . Do not interpret asset base as financeable contract revenue.

Manual or pull-request workflow only. No cron, no new ChatGPT task, no changes to LIFE OS or automated trading jobs. 

### Source reliability finding

DailyDAC public WordPress RSS may return HTTP 403 to hosted GitHub runners. We do not bypass it. Source errors are explicit in the JSON. As independent free fallback, Google News public RSS is polled read-only with a 30-day query and hard 45-day publication age filter. This feed is NEWS DISCOVERY ONLY: no direct primary sale notice, approved bid deadline, or verified purchase opportunity. If any optional source fails, the combined report is PARTIAL_PUBLIC_NOTICE_COVERAGE, not a full green source-coverage claim; mandatory court failure or complete public notice discovery failure is an operational failure. The job still does no paid PACER requests and opens no news links.

One live source sample surfaced 8 free public-notice index entries (many expired or unrelated) while another returned HTTP 403. No direct, financeable, transferable-contract sale has been verified. A separate manual source check identified Noble Supply & Logistics as an acquisition research candidate with published October 30 bid date, but bids require 10% deposit, proven financing and contract cure obligations. Reference: https://app.bondoro.com/preview/cases/Noble_Supply__Logistics_LLC/apa-summary . Not a recommendation to bid or proof of affordability.
