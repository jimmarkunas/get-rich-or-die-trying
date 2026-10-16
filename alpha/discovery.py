"""Read-only discovery of NO/NO collateral-bound candidates in exclusive Kalshi events.

An event's exchange-provided mutually_exclusive flag means at most one YES
can win. For two distinct normal binary markets in that SAME event, buying
NO in both has a conditional lower bound of $1 on $2 of contracts. It does
NOT mean that buying every YES is guaranteed to pay. Exchange metadata cannot
rule out all exception clauses, nonstandard settlements, cancelled events,
execution slippage or quote changes, so alerts explicitly require review.
"""
import hashlib
from datetime import datetime, timezone
import json
import re
import time
from decimal import Decimal
from itertools import combinations
from .common import D, Observation, request_json, utc_now
from .kalshi import BASE, fetch_book, quote_purchase

TICKER = re.compile(r'^[A-Z0-9._-]{1,128}$')
# Terms with potential settlement exceptions; conservative, intentionally broad.
EXCEPTION_TERMS = re.compile(r'\b(refund|void|cancell?ed|fair\s+(?:market\s+)?value|partial\s+payout|prorat|split|draw|tie|dead\s+heat|reimburse)\b', re.I)


def fetch_event_pages(*, max_pages=2, page_size=100, series=None):
    if not 1 <= max_pages <= 10 or not 1 <= page_size <= 200:
        raise ValueError('invalid discovery budget')
    if series is not None and not re.fullmatch(r'[A-Z0-9_-]{1,64}', series):
        raise ValueError('invalid series')
    cursor = None
    events = []
    seen_cursors = set()
    for _ in range(max_pages):
        params = {'status': 'open', 'limit': page_size, 'with_nested_markets': 'true'}
        if series: params['series_ticker'] = series
        if cursor: params['cursor'] = cursor
        body = request_json(BASE + '/events', params=params)
        if not isinstance(body, dict) or not isinstance(body.get('events'), list):
            raise ValueError('event API schema changed')
        events.extend(body['events'])
        nxt = body.get('cursor') or None
        if not nxt: break
        if not isinstance(nxt, str) or nxt in seen_cursors:
            raise ValueError('repeated or malformed event pagination cursor')
        seen_cursors.add(nxt)
        cursor = nxt
    return events


def standard_binary_market(event_ticker, market):
    """Fail-closed metadata screening, not a replacement for full contract review."""
    if not isinstance(market, dict): return False
    ticker = market.get('ticker', '')
    if not isinstance(ticker, str) or not TICKER.fullmatch(ticker): return False
    if market.get('event_ticker') != event_ticker: return False
    if market.get('status') != 'active': return False
    if market.get('market_type') != 'binary': return False
    if market.get('settlement_bounds_type') != 'default': return False
    if market.get('is_provisional') is True: return False
    if market.get('mve_collection_ticker') or market.get('mve_selected_legs'): return False
    if market.get('settlement_floor_dollars') not in (None, '0.0000', '0.00', '0'):
        return False
    if not isinstance(market.get('rules_primary'), str) or not market['rules_primary'].strip(): return False
    rules = market['rules_primary'] + '\n' + str(market.get('rules_secondary') or '')
    if EXCEPTION_TERMS.search(rules): return False
    return True


def eligible_event(event):
    if not isinstance(event, dict) or event.get('mutually_exclusive') is not True: return []
    ev = event.get('event_ticker', '')
    if not isinstance(ev, str) or not TICKER.fullmatch(ev): return []
    if event.get('fee_type_override') not in (None, '', 'standard'): return []
    if event.get('fee_multiplier_override') not in (None, 1, '1'): return []
    markets = event.get('markets')
    if not isinstance(markets, list): return []
    accepted = [m for m in markets if standard_binary_market(ev, m)]
    return accepted if len(accepted) >= 2 else []


def metadata_digest(event, pair):
    body = {'event_ticker':event['event_ticker'],'mutually_exclusive':True,'contracts':[]}
    for market in sorted(pair, key=lambda x: x['ticker']):
        body['contracts'].append({key:market.get(key) for key in
            ('ticker', 'rules_primary', 'rules_secondary', 'market_type', 'settlement_bounds_type', 'settlement_floor_dollars')})
    return hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def indicative_no_ask(market):
    try:
        raw=market.get('no_ask_dollars')
        if raw is None or raw=='':
            # Public market listing sometimes exposes the corresponding YES bid instead.
            bid=D(market['yes_bid_dollars'])
            n=D(1)-bid
        else:
            n=D(raw)
        return n if n.is_finite() and 0 < n < 1 else D(2)
    except (KeyError, ValueError, TypeError, ArithmeticError):
        return D(2)


def scan_exclusive_events(*, quantity=10, quantities=None, buffer_usd='0.25', fee_rate='0.07',
                          max_pages=2, max_events=12, max_pairs_per_event=2,
                          max_book_age_seconds=18, series=None):
    if not isinstance(quantity, int) or not 1 <= quantity <= 500:
        raise ValueError('invalid quantity')
    amounts=sorted(set(quantities if quantities is not None else [quantity]))
    if not 1 <= len(amounts) <= 5 or any(not isinstance(x,int) or not 1<=x<=500 for x in amounts):
        raise ValueError('invalid sizing exploration')
    if not 1 <= max_events <= 50 or not 1 <= max_pairs_per_event <= 10:
        raise ValueError('invalid scan caps')
    if D(buffer_usd) < 0 or D(fee_rate) < 0:
        raise ValueError('invalid cost assumptions')
    events = fetch_event_pages(max_pages=max_pages, series=series)
    observations = []
    errors = {}
    candidates = []
    for ev in events:
        accepted = eligible_event(ev)
        if not accepted: continue
        # Cheap NO indicative asks are only ranking hints, never used for P&L.
        ranked = sorted(accepted, key=lambda m:(indicative_no_ask(m),m['ticker']))[:8]
        pairs = sorted(combinations(ranked, 2),key=lambda pp:(sum(indicative_no_ask(m) for m in pp),pp[0]['ticker'],pp[1]['ticker']))
        if pairs: candidates.append((pairs[0][0]['ticker'],ev,pairs[:max_pairs_per_event]))
    # Evaluate cheapest *indicative* markets first, NOT alphabetical ticker order.
    # Hints rank event fetches; final P&L still derives exclusively from orderbooks.
    def event_rank(item):
        _,ev,pairs=item
        min_asks=sum(indicative_no_ask(m) for m in pairs[0])
        # Secondary tie-breaker: prefer higher available liquidity when published.
        liqs=[]
        for m in pairs[0]:
            try: liqs.append(max(D(0),D(m.get('liquidity_dollars',0))))
            except (TypeError,ValueError,ArithmeticError): liqs.append(D(0))
        # Rotate tied/unpriced events across hourly scans rather than starving
        # later alphabetic tickers forever. Never used to calculate a return.
        hour=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H')
        rotation=hashlib.sha256((hour+ev['event_ticker']).encode()).hexdigest()
        return (min_asks,-min(liqs),rotation)
    # Bounded upstream discovery, with no implied completeness.
    for _,ev,pairs in sorted(candidates,key=event_rank)[:max_events]:
        for pair in pairs:
            cache = {}  # fresh independent orderbooks per pair; no cross-pair staleness
            tickers = sorted(m['ticker'] for m in pair)
            digest = metadata_digest(ev,pair)
            start = time.monotonic()
            try:
                for ticker in tickers:
                    if ticker not in cache: cache[ticker] = fetch_book(ticker)
                elapsed = time.monotonic()-start
                if elapsed > max_book_age_seconds:
                    raise TimeoutError('quotes sampled over stale time window')
                for amount in amounts:
                    quotes = [quote_purchase(cache[t], 'no',amount,fee_rate) for t in tickers]
                    if any(q is None for q in quotes):
                        cls = 'insufficient_depth'; net = None; cost = None; fees = None
                    else:
                        cost = sum((q['cost'] for q in quotes),Decimal(0))
                        fees = sum((q['fees'] for q in quotes),Decimal(0))
                        net = D(amount) - cost - fees - D(buffer_usd)
                        cls = 'candidate_rule_review_required' if net > 0 else 'no_positive_guarded_edge'
                    observations.append(Observation('kalshi',ev['event_ticker']+':'+','.join(tickers)+':qty='+str(amount),utc_now(),cls,
                        str(net) if net is not None else None,
                        {'kind':'two_no_mutually_exclusive_lower_bound','event_ticker':ev['event_ticker'],
                         'tickers':tickers,'side':'no','quantity':amount,'estimated_cost':str(cost) if cost is not None else None,
                         'estimated_fees':str(fees) if fees is not None else None,'buffer_usd':str(buffer_usd),
                         'conditional_payout_floor_usd':str(amount),'metadata_sha256':digest,
                         'exchange_mutually_exclusive':True,'rules_automatically_screened':True,
                         'full_rulebook_manual_review_required':True,'quotes_nonatomic':True,
                         'not_executable_or_guaranteed':True,'fee_schedule_assumed':True,
                         'quote_window_seconds':round(elapsed,3),'sampling_method':'indicative_ask_ranked_with_liquidity_tiebreak'},BASE+'/events'))
            except Exception as e:
                errors[ev['event_ticker']+':'+','.join(tickers)] = type(e).__name__+': '+str(e)
    observations.append(Observation('kalshi','exclusive-discovery',utc_now(),
        'discovery_heartbeat',None,{'events_examined':len(events),'eligible_events':len(candidates),
        'priced_scenarios':len(observations),'distinct_pairs':len({tuple(x.details.get('tickers',[])) for x in observations}),'errors':len(errors),'candidate_count':sum(x.classification=='candidate_rule_review_required' for x in observations)},BASE+'/events'))
    return observations,errors
