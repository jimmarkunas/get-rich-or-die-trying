"""Kalshi read-only binary contract checks; NO order submission.

A single-market YES+NO basket generally cannot be bought below $1 on a
consistent order book. Multi-market baskets require explicit external proof that
their YES payoffs sum to exactly one. This scanner never infers that from titles.
"""
from decimal import Decimal, ROUND_CEILING
from math import floor
from urllib.parse import quote
from .common import D, Observation, request_json, utc_now

BASE='https://external-api.kalshi.com/trade-api/v2'


def fee(cost_price,contracts,rate='0.07'):
    """Approximate default taker fee, rounded up to a cent per leg.

    Special categories/market-specific schedules may differ. Not a firm fee quote.
    """
    p=D(cost_price)
    if not 0 <= p <= 1 or contracts < 0:
        raise ValueError('bad price/contracts')
    return (D(rate) * D(contracts) * p * (1-p)).quantize(D('.01'),rounding=ROUND_CEILING)


def parse_bids(book,side):
    fp=book.get('orderbook_fp')
    if not isinstance(fp,dict):
        raise ValueError('orderbook_fp absent; obsolete or invalid Kalshi schema')
    levels=fp.get(f'{side}_dollars')
    if levels is None:
        raise ValueError(f'{side} prices absent')
    out=[]
    for level in levels:
        if len(level)!=2:
            raise ValueError('invalid bid level')
        price,qty=map(D,level)
        if not 0 < price < 1 or qty < 0:
            raise ValueError('invalid level price/size')
        n=int(qty)
        if n>0:
            out.append((price,n))
    return sorted(out,key=lambda x:x[0],reverse=True)


def ask_levels(book,side):
    """Opposite bids imply our ask prices and available sizes."""
    bids=parse_bids(book,'no' if side=='yes' else 'yes')
    return sorted([(D(1)-price,size) for price,size in bids],key=lambda x:x[0])


def quote_purchase(book,side,contracts,taker_rate='0.07'):
    if contracts<=0 or not isinstance(contracts,int):
        raise ValueError('contracts must be positive whole units')
    levels=ask_levels(book,side)
    remaining=contracts
    cost=D(0); fees=D(0)
    for price,sz in levels:
        if remaining==0: break
        n=min(remaining,sz)
        cost+=price*n
        fees+=fee(price,n,taker_rate)
        remaining-=n
    if remaining:
        return None  # no misleading partial fill
    return {'cost':cost,'fees':fees,'total':cost+fees,'contracts':contracts}


def basket_quote(legs,books,contracts,taker_rate='0.07',buffer_usd='0'):
    """All legs pay a total of $1 only for a separately verified exact partition.

    `legs` is a list of {'ticker':'...', 'side':'yes|no'}.
    Caller *must* explicitly mark payout identity independently verified.
    """
    if len(legs)<2 or not isinstance(contracts,int) or contracts<=0:
        raise ValueError('invalid basket')
    seen=set(); totals=[]
    for leg in legs:
        ticker=leg['ticker']; side=leg['side']
        if side not in ('yes','no') or (ticker,side) in seen:
            raise ValueError('invalid or duplicate leg')
        seen.add((ticker,side))
    for ticker,side in seen:
        if ticker not in books: return None
        quote=quote_purchase(books[ticker],side,contracts,taker_rate)
        if quote is None: return None
        totals.append(quote)
    cost=sum((q['cost'] for q in totals),D(0))
    fees=sum((q['fees'] for q in totals),D(0))
    gross=D(contracts)-cost
    net=gross-fees-D(buffer_usd)
    return {'gross':gross,'fees':fees,'cost':cost,'net':net,'contracts':contracts}


def fetch_markets(series,limit=20):
    if not series or not series.isalnum(): raise ValueError('invalid series ticker')
    data=request_json(BASE+'/markets',params={'series_ticker':series,'status':'open','limit':min(limit,1000)})
    if not isinstance(data.get('markets'),list): raise ValueError('markets schema changed')
    return data['markets'][:limit]


def fetch_book(ticker):
    if not ticker or not all(c.isalnum() or c=='-' for c in ticker): raise ValueError('invalid ticker')
    return request_json(f'{BASE}/markets/{quote(ticker,safe="")}/orderbook')


def scan_kalshi(*,series=None,tickers=(),groups=(),quantity=10,fee_rate='0.07',buffer_usd='0',max_markets=15):
    markets=fetch_markets(series,max_markets) if series else []
    # Explicit targets take precedence over generic series discovery, never silently lose them.
    requested=list(dict.fromkeys(list(tickers)+[leg['ticker'] for g in groups for leg in g.get('legs',[])]+[m['ticker'] for m in markets]))
    if len(requested)>max_markets:
        explicit=set(tickers)|{leg['ticker'] for g in groups for leg in g.get('legs',[])}
        if len(explicit)>max_markets:
            raise ValueError('max_markets too small for all explicitly requested tickers')
        requested=requested[:max_markets]
    books={};errors={}
    for ticker in requested:
        try: books[ticker]=fetch_book(ticker)
        except Exception as e: errors[ticker]=f'{type(e).__name__}: {e}'
    observations=[]
    if series and not markets:
        # A valid empty market response is distinct from a failed API call. This
        # heartbeat proves the market listing API responded but is not a trade.
        observations.append(Observation('kalshi',series,utc_now(),
          'no_open_markets_in_configured_series',None,
          {'kind':'series_market_discovery','requested_max_markets':max_markets,
           'no_trade_opportunity_inferred':True},BASE))
    for ticker,book in books.items():
        # Diagnostic only. No claim that two crossing legs can be filled simultaneously.
        q=basket_quote([{'ticker':ticker,'side':'yes'},{'ticker':ticker,'side':'no'}],books,quantity,fee_rate,buffer_usd)
        observations.append(Observation('kalshi',ticker,utc_now(),'diagnostic_not_executable',str(q['net']) if q else None,
          {'kind':'same_market_complement','quantity':quantity,'filled_quote':bool(q),'fees_are_estimated':True,'quotes_not_atomic':True},BASE))
    for group in groups:
        name=group.get('name','unnamed')
        verified=group.get('payout_partition_verified') is True
        # NEVER interpret similarly titled markets as mutually exclusive.
        q=basket_quote(group['legs'],books,quantity,fee_rate,buffer_usd)
        classification=('candidate_manual_execution_risk' if verified and q and q['net']>0 else
                        'unverified_payout_partition' if not verified else 'insufficient_liquidity_or_no_edge')
        observations.append(Observation('kalshi',name,utc_now(),classification,str(q['net']) if q else None,
          {'legs':group['legs'],'quantity':quantity,'payout_partition_verified_by_user':verified,
           'quote':{k:str(v) for k,v in q.items()} if q else None,'fees_are_estimated':True,
           'quotes_not_atomic':True,'manual_rule_review_required':True},BASE))
    return observations,errors
