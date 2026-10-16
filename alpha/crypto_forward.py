"""Forward-only paper portfolios; best public bid/ask + adverse slippage; never orders.

No wallet, credentials, trading SDK, order POST, derivatives, or leverage.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from .crypto_data import fetch_candles, fetch_book_ticker, SYMBOLS, HOUR_MS
from .crypto_strategy import portfolio, decision, execute, snapshot, mark

STATE_VERSION = 1
FIELDS = ('cash','units','cost_basis','entry_price','fees','slippage_cost','turnover_usd',
          'trades','wins','losses','peak_equity','max_drawdown_pct','exposure_bars','bars')
DECIMALS = {'cash','units','cost_basis','entry_price','fees','slippage_cost',
            'turnover_usd','peak_equity','max_drawdown_pct'}


def serialize(state):
    return {k:(str(state[k]) if k in DECIMALS and state[k] is not None else state[k]) for k in FIELDS}


def deserialize(raw):
    if set(raw) != set(FIELDS):
        raise ValueError('paper portfolio schema mismatch')
    p={k:(Decimal(str(v)) if k in DECIMALS and v is not None else v) for k,v in raw.items()}
    if p['cash'] < 0 or p['units'] < 0 or p['fees'] < 0 or p['peak_equity'] <= 0:
        raise ValueError('invalid paper portfolio state')
    if not all(isinstance(p[k],int) and p[k]>=0 for k in ('trades','wins','losses','exposure_bars','bars')):
        raise ValueError('invalid integer accounting')
    return p


def create_state():
    return {'version':STATE_VERSION,'symbols':{}}


def paper_cycle(previous=None, symbols=SYMBOLS, candle_reader=fetch_candles,
                quote_reader=fetch_book_ticker, observed_at=None):
    """Process one current quote per symbol when a NEW closed candle appears.

    If process misses >2 bars, we refuse to manufacture backdated paper fills.
    If first seen, merely establish a baseline and start forward on NEXT run.
    """
    prev=deepcopy(previous or create_state())
    if prev.get('version') != STATE_VERSION or not isinstance(prev.get('symbols'),dict):
        raise ValueError('unknown paper state version')
    now=observed_at or datetime.now(timezone.utc).isoformat()
    output=[]
    for symbol in symbols:
        if symbol not in SYMBOLS:raise ValueError('invalid spot symbol')
        bars=candle_reader(symbol,120)
        if len(bars)!=120:raise ValueError('missing current candle warmup')
        quote=quote_reader(symbol)
        latest=bars[-1].timestamp_ms
        existing=prev['symbols'].get(symbol)
        if existing is None:
            prev['symbols'][symbol]={'last_closed_open_ms':latest,
                'portfolios':{x:serialize(portfolio()) for x in ('momentum','grid')}}
            output.append({'symbol':symbol,'observed_at_utc':now,'bar_open_ms':latest,
                'status':'seeded_no_backdated_trades','paper_trades':0})
            continue
        last=int(existing['last_closed_open_ms'])
        if latest < last:raise ValueError('feed moved backward')
        if latest == last:
            output.append({'symbol':symbol,'observed_at_utc':now,'bar_open_ms':latest,
                'status':'already_processed','paper_trades':0})
            continue
        # A scanner that was offline cannot claim it could have filled trades at historical quotes.
        gap=latest-last
        missed=gap > 2*HOUR_MS
        for strategy in ('momentum','grid'):
            current=deserialize(existing['portfolios'][strategy])
            action='hold' if missed else decision(strategy,bars,current['units']>0,current['entry_price'])
            fill=None
            if action != 'hold':
                # Current public quote, NOT candle open and NOT a guaranteed execution.
                is_buy=action=='buy'
                px=quote['ask'] if is_buy else quote['bid']
                qty=quote['ask_qty'] if is_buy else quote['bid_qty']
                fill=execute(current,action,px,bars[-1].volume,max_units=qty)
            equity=mark(current,quote['bid'])
            existing['portfolios'][strategy]=serialize(current)
            output.append({'symbol':symbol,'strategy':strategy,'observed_at_utc':now,
                'bar_open_ms':latest,'status':'stale_gap_skipped' if missed else 'paper_evaluated',
                'signal':action,'simulated_fill':fill,'paper_trades':int(fill is not None),
                'quote_bid':str(quote['bid']),'quote_ask':str(quote['ask']),
                'snapshot':snapshot(current,quote['bid']),
                'not_actual_fill':True,'no_orders_submitted':True})
        existing['last_closed_open_ms']=latest
    return prev,output
