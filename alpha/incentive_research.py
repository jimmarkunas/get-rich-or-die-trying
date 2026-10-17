"""Public-data-only Kalshi liquidity reward feasibility study.

Never places or stages orders. Never assumes reward pool equals personal income.
Qualifying analysis observes one public book, NOT Kalshi's historical random
snapshots or a real position in the exchange queue. An actual user must review
account/geography/market eligibility and current regulatory notices.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from pathlib import Path
from urllib.parse import quote

from .common import request_json

BASE = 'https://external-api.kalshi.com/trade-api/v2'
TICKER = re.compile(r'^[A-Z0-9._-]{1,128}$')


def D(x):
    try:
        d = Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError('invalid numeric field') from exc
    if not d.is_finite():
        raise ValueError('non-finite field')
    return d


def timestamp(s):
    if not isinstance(s, str):
        raise ValueError('missing incentive period timestamp')
    try:
        d = datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('invalid incentive date') from exc
    if d.tzinfo is None:
        raise ValueError('naive incentive date')
    return d.astimezone(timezone.utc)


def active_incentives(*, now=None, pages=3, page_size=300, getter=request_json):
    """Bounded, paginated public GET. Server status is cross-checked with dates."""
    if not 1 <= pages <= 10 or not 1 <= page_size <= 1000:
        raise ValueError('unsafe pagination bounds')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise ValueError('now must be timezone-aware')
    cursor = None
    seen_cursors = set()
    seen_ids = set()
    rows = []
    exhausted = False
    for _ in range(pages):
        params = {'status':'active','type':'liquidity','limit':page_size}
        if cursor: params['cursor'] = cursor
        response = getter(BASE + '/incentive_programs', params=params)
        if not isinstance(response, dict) or not isinstance(response.get('incentive_programs'),list):
            raise ValueError('incentives API schema mismatch')
        for program in response['incentive_programs']:
            if not isinstance(program,dict) or program.get('incentive_type') != 'liquidity': continue
            try:
                ident = program['id']
                ticker = program['market_ticker']
                if not isinstance(ident,str) or not ident or not isinstance(ticker,str) or not TICKER.fullmatch(ticker):continue
                if not timestamp(program['start_date']) <= now < timestamp(program['end_date']):continue
                target = D(program['target_size_fp'])
                factor = D(program['discount_factor_bps'])
                reward = D(program['period_reward'])
                if target <= 0 or not 0 <= factor <= 10000 or reward < 0: continue
            except (KeyError,ValueError):
                continue
            if ident not in seen_ids:
                seen_ids.add(ident)
                rows.append(program)
        nxt = response.get('next_cursor')
        if not nxt:
            exhausted = True
            break
        if not isinstance(nxt,str) or nxt in seen_cursors or len(nxt)>2048:
            raise ValueError('invalid pagination cursor')
        seen_cursors.add(nxt)
        cursor=nxt
    return rows, {'pages_cap':pages,'pages_exhausted':exhausted,'truncated_pagination':not exhausted,
                  'active_liquidity_programs_examined':len(rows)}


def parse_book(book):
    fp=book.get('orderbook_fp') if isinstance(book,dict) else None
    if not isinstance(fp,dict):raise ValueError('orderbook_fp schema mismatch')
    out={}
    for side in ('yes','no'):
        levels=fp.get(side+'_dollars')
        if not isinstance(levels,list):raise ValueError('missing '+side+' book')
        entries=[]
        for level in levels:
            if not isinstance(level,(tuple,list)) or len(level)!=2:raise ValueError('invalid book level')
            price,qty=map(D,level)
            if not 0 < price < 1 or qty < 0:raise ValueError('invalid price or quantity')
            if qty:entries.append((price,qty))
        out[side]=sorted(entries,reverse=True)
    return out


def bid_depth(levels):
    return sum((qty for price,qty in levels),Decimal(0))


def hypothetical_quote(levels, other_levels, target, budget, max_contracts):
    """Join existing best bid only; never claim priority or reward qualification.

    A real order may fill, be rejected, or never qualify at random snapshots.
    The returned score only tests two-sided *visible depth*, not payout.
    """
    if not levels or not other_levels:return {'status':'no_two_sided_quotes'}
    best=levels[0][0]
    best_other=other_levels[0][0]
    if best + best_other >= 1: return {'status':'crossed_or_locked_quotes'}
    # Join an existing published price, avoiding tick-size assumptions.
    if not D('.05') <= best <= D('.95'):return {'status':'outside_research_price_band'}
    max_possible=min(Decimal(max_contracts),(budget/best).to_integral_value(rounding=ROUND_FLOOR))
    if max_possible < 1:return {'status':'insufficient_research_budget'}
    quantity=int(max_possible)
    exposed=D(quantity)*best
    our_depth=bid_depth(levels)+D(quantity)
    other_depth=bid_depth(other_levels)
    return {'status':'visible_book_meets_depth_gate_personal_qualification_unknown'
                    if our_depth>=target and other_depth>=target else 'insufficient_two_sided_target_depth',
            'join_price_dollars':str(best),'hypothetical_contracts':quantity,
            'max_cash_committed_if_posted_usd':str(exposed),
            'max_principal_loss_if_all_fill_and_settle_zero_usd':str(exposed),
            'visible_own_side_depth_before':str(bid_depth(levels)),
            'visible_own_side_depth_after':str(our_depth),
            'visible_opposite_side_depth':str(other_depth),
            'target_size_contracts':str(target),'join_queue_priority_known':False,
            'user_order_exists':False,'personal_reward_estimate_usd':None,
            'snapshot_eligibility_proven':False}


def analyze_program(program, book, *, budget='100', max_contracts=50):
    if not isinstance(program,dict):raise ValueError('bad program')
    limit=D(budget)
    if not 0 < limit <= 1000 or not isinstance(max_contracts,int) or not 1 <= max_contracts <= 500:
        raise ValueError('unsafe research scenario')
    target=D(program['target_size_fp'])
    if target<=0:raise ValueError('invalid target')
    levels=parse_book(book)
    a={side:hypothetical_quote(levels[side],levels['no' if side=='yes' else 'yes'],target,limit,max_contracts)
       for side in ('yes','no')}
    start=timestamp(program['start_date']); end=timestamp(program['end_date'])
    hours=D((end-start).total_seconds())/D(3600)
    if hours<=0:raise ValueError('invalid period length')
    # Kalshi API currently exposes period_reward as an integer with no unit
    # declaration on its public docs page; DO NOT turn this into alleged USD.
    return {'program_id':program['id'],'market_ticker':program['market_ticker'],
            'incentive_type':'liquidity','period_start_utc':start.isoformat(),
            'period_end_utc':end.isoformat(),'period_hours':str(hours),
            'period_reward_api_raw':str(D(program['period_reward'])),
            'reward_currency_unit_verified':False,
            'period_reward_usd_verified':None,
            'target_size_fp':str(target),
            'discount_factor_bps':str(D(program['discount_factor_bps'])),
            'hypothetical_budget_per_side_usd':str(limit),
            'book':{'visible_yes_bid_depth':str(bid_depth(levels['yes'])),
                    'visible_no_bid_depth':str(bid_depth(levels['no'])),
                    'both_sides_already_reach_target':bool(bid_depth(levels['yes'])>=target and bid_depth(levels['no'])>=target)},
            'simulated_yes_bid':a['yes'],'simulated_no_bid':a['no'],
            'qualified_random_snapshot_count':None,'hypothetical_payout_usd':None,
            'expected_trading_net_usd':None,'actual_payout_usd':0,
            'outcome':'depth_feasibility_only_not_profit_prediction',
            'account_and_illinois_market_eligibility':'unverified',
            'resting_order_fill_risk':'full_quote_principal_can_be_lost',
            'source':'public Kalshi incentive program and visible orderbook'}


def scan(*, pages=3, page_size=300, max_books=12, budget='100', max_contracts=50,
         getter=request_json, now=None):
    if not 1 <= max_books <= 30:raise ValueError('unsafe book fetch cap')
    programs,meta=active_incentives(pages=pages,page_size=page_size,now=now,getter=getter)
    by_ticker={}
    for p in programs:
        t=p['market_ticker']
        # multiple overlapping rewards can exist. Inspect per program, but
        # cap distinct market book requests and don't double-count income.
        by_ticker.setdefault(t,[]).append(p)
    ranked=sorted(by_ticker.items(),key=lambda it:(-max(D(x['period_reward']) for x in it[1]),it[0]))
    selected=ranked[:max_books]
    observations=[]; errors={}
    for ticker, programs_for_market in selected:
        try:
            book=getter(BASE+'/markets/'+quote(ticker,safe='')+'/orderbook')
            for program in programs_for_market:
                observations.append(analyze_program(program,book,budget=budget,max_contracts=max_contracts))
        except Exception as exc:
            errors[ticker]=type(exc).__name__+': '+str(exc)
    return {'observed_at_utc':(now or datetime.now(timezone.utc)).isoformat(),
            'mode':'read_only_public_market_feasibility','live_orders_submitted':0,
            'actual_rewards_earned_usd':0,'personal_reward_forecasts_available':False,
            'assumed_cash_limit_per_side_usd':str(D(budget)),
            'programs_available':len(programs),'distinct_markets_available':len(ranked),
            'distinct_markets_sampled':len(selected),'programs_analyzed':len(observations),
            'truncated_market_selection':len(ranked)>len(selected),
            'pagination':meta,'samples':observations,'errors':errors,
            'feasible_visible_joins':sum(sum(row[k].get('status')=='visible_book_meets_depth_gate_personal_qualification_unknown'
                                                  for k in ('simulated_yes_bid','simulated_no_bid')) for row in observations),
            'cannot_claim_income_without':'actual rest orders, snapshot scores, member eligibility, reward-unit verification, and filled-order P&L'}


def cli(argv=None):
    p=argparse.ArgumentParser(description='Kalshi public liquidity-incentive feasibility; NEVER trades')
    p.add_argument('--pages',type=int,default=3)
    p.add_argument('--page-size',type=int,default=300)
    p.add_argument('--max-books',type=int,default=12)
    p.add_argument('--budget',default='100')
    p.add_argument('--max-contracts',type=int,default=50)
    p.add_argument('--out',default='output/kalshi-incentives.json')
    a=p.parse_args(argv)
    result=scan(pages=a.pages,page_size=a.page_size,max_books=a.max_books,
                budget=a.budget,max_contracts=a.max_contracts)
    target=Path(a.out);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'programs_available':result['programs_available'],
                      'markets_sampled':result['distinct_markets_sampled'],
                      'feasible_visible_joins':result['feasible_visible_joins'],
                      'errors':len(result['errors']),'orders':0,'rewards_earned_usd':0}))
    # A complete fetch failure is NOT an honest zero-opportunity result.
    if result['distinct_markets_sampled'] and result['programs_analyzed']==0:
        raise RuntimeError('all incentive order-book requests failed')
    return 0


if __name__ == '__main__':raise SystemExit(cli())
