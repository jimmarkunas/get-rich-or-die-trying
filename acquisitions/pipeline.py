"""One read-only acquisition discovery report across official feeds and free notices."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from acquisitions.scout import scan as scan_courts
from acquisitions.notices import scan_notice_sources

def run() -> dict:
    court = scan_courts()
    notices = scan_notice_sources()
    remaining_public_sources = len(notices["sources_checked"]) - len(notices["source_errors"])
    coverage = ("FAILED_ALL_PUBLIC_NOTICE_SOURCES" if remaining_public_sources == 0
                else "PARTIAL_PUBLIC_NOTICE_COVERAGE" if notices["source_errors"]
                else "ALL_SOURCE_ENDPOINTS_RESPONDED")
    return {
        "source_coverage": coverage,
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "RESEARCH_ONLY_NO_ACQUISITION_OR_REVENUE_PROVEN",
        "pacer_requests": 0,
        "pacer_fees_usd": 0,
        "automated_bids": 0,
        "automated_seller_contacts": 0,
        "verified_financeable_acquisitions": 0,
        "court_docket": court,
        "public_sale_notices": notices,
        "claims_agent_directories": [
            {"name": "Epiq public case index", "url": "https://dm.epiq11.com/",
             "status": "MANUAL_REFERENCE_NOT_AUTOMATICALLY_PARSED"},
            {"name": "Kroll public case index", "url": "https://www.kroll.com/en/restructuring-administration-cases",
             "status": "MANUAL_REFERENCE_NOT_AUTOMATICALLY_PARSED"},
        ],
        "decision_gate": "Validate free source notice and current court order; verify bid price, asset schedule, assigned contracts, cure, buyer cash, lender commitment.",
    }

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default="output/acquisitions/illinois-latest.json")
    args = p.parse_args(argv)
    report = run()
    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({
        "pacer_requests": 0,
        "court_errors": report["court_docket"]["courts_failed"],
        "public_notice_errors": report["public_sale_notices"]["source_errors"],
        "court_matches": report["court_docket"]["potential_docket_leads"],
        "free_sale_notices": report["public_sale_notices"]["free_sale_notice_matches"],
        "future_unconfirmed_dates": report["public_sale_notices"]["future_bid_dates_unconfirmed"],
        "verified_financeable_acquisitions": 0,
        "source_coverage": report["source_coverage"],
    }, sort_keys=True))
    # Third-party 403 remains prominently DEGRADED but is nonfatal when an
    # independent public source responded. Mandatory official court failures fail.
    return 2 if (report["court_docket"]["courts_failed"] or
                 report["source_coverage"] == "FAILED_ALL_PUBLIC_NOTICE_SOURCES") else 0

if __name__ == "__main__":
    raise SystemExit(main())
