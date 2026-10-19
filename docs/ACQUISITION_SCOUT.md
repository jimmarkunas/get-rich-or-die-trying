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
