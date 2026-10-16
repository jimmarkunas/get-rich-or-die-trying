"""Honest long-only candle-based research with explicit next-bar simulated execution.

The grid model is intentionally a *grid-style mean-reversion signal* filled as
conservative TAKERS, not a fictional zero-fee or queue-priority maker fill.
"""
from decimal import Decimal
from .crypto_data import number, HOUR_MS

STARTING_CASH = Decimal('1000')
FEE_RATE = Decimal('0.0002')          # Binance.US published non-VIP taker fee, other pairs
SLIPPAGE_RATE = Decimal('0.0005')     # assumption: adverse price movement per side
NOTIONAL_FRACTION = Decimal('0.25')  # cap allocation per symbol to 25% equity
VOLUME_SHARE_CAP = Decimal('0.01')   # at most 1% of reported last hourly volume
MIN_NOTIONAL = Decimal('10')
WARMUP = 50


def average(items):
    return sum(items, Decimal(0)) / Decimal(len(items))


def decision(strategy, prior, held, entry_price=None):
    """Uses ONLY bars already closed, never the candle about to execute."""
    if strategy not in ('momentum', 'grid'):
        raise ValueError('unknown strategy')
    if len(prior) < WARMUP:
        return 'hold'
    p = prior[-1].close
    if strategy == 'momentum':
        fast = average([c.close for c in prior[-12:]])
        slow = average([c.close for c in prior[-48:]])
        rising = p > fast > slow and p > prior[-13].close * Decimal('1.01')
        falling = p < fast or fast < slow
        if not held and rising: return 'buy'
        if held and (falling or (entry_price is not None and p < entry_price * Decimal('0.97'))): return 'sell'
    else:
        # A signal-based reversion grid, not resting maker orders. No inside-bar fills.
        center = average([c.close for c in prior[-24:]])
        if not held and p < center * Decimal('0.9925'): return 'buy'
        if held and (p > center * Decimal('1.0075') or
                     (entry_price is not None and p < entry_price * Decimal('0.965'))): return 'sell'
    return 'hold'


def portfolio(cash=STARTING_CASH):
    return {'cash':number(cash), 'units':Decimal(0), 'cost_basis':Decimal(0),
            'entry_price':None, 'fees':Decimal(0), 'slippage_cost':Decimal(0),
            'turnover_usd':Decimal(0), 'trades':0, 'wins':0, 'losses':0,
            'peak_equity':number(cash), 'max_drawdown_pct':Decimal(0),
            'exposure_bars':0, 'bars':0}


def execute(state, action, reference, volume, fee_rate=FEE_RATE,
            slippage=SLIPPAGE_RATE, max_units=None):
    """Compute conservative simulated taker fills at next open or observed quote.

    reference is the bar open for backtests, and public best ask (buy) or bid
    (sell) for forward paper simulation. Never accepts leverage/short positions.
    """
    reference = number(reference); volume = number(volume)
    fee_rate=number(fee_rate); slippage=number(slippage)
    if reference <= 0 or volume <= 0 or not 0 <= fee_rate <= Decimal('.01') or not 0 <= slippage <= Decimal('.05'):
        return None
    if action == 'buy' and state['units'] == 0:
        px = reference*(1+slippage)
        notional = min(state['cash']*NOTIONAL_FRACTION, volume*VOLUME_SHARE_CAP*px)
        if max_units is not None:
            notional = min(notional, number(max_units)*px)
        if notional < MIN_NOTIONAL:
            return None
        units = notional/px
        cost = units*px
        fee = cost*fee_rate
        if cost+fee > state['cash']:
            units=state['cash']/(px*(1+fee_rate))
            cost=units*px
            fee=cost*fee_rate
        state['cash'] -= cost+fee
        state['units']=units
        state['cost_basis']=cost+fee
        state['entry_price']=px
        state['fees']+=fee
        state['slippage_cost']+=reference*slippage*units
        state['turnover_usd']+=cost
        state['trades']+=1
        return {'action':'buy','price':str(px),'units':str(units),'gross_usd':str(cost),'fee_usd':str(fee)}
    if action == 'sell' and state['units'] > 0:
        units = state['units']
        # A top-of-book quantity cap disallows optimistic forward executions.
        if max_units is not None and number(max_units) < units:
            return None
        px=reference*(1-slippage)
        proceeds=units*px
        fee=proceeds*fee_rate
        net=proceeds-fee
        if net > state['cost_basis']: state['wins']+=1
        else:state['losses']+=1
        state['cash']+=net
        state['units']=Decimal(0)
        state['cost_basis']=Decimal(0)
        state['entry_price']=None
        state['fees']+=fee
        state['slippage_cost']+=reference*slippage*units
        state['turnover_usd']+=proceeds
        state['trades']+=1
        return {'action':'sell','price':str(px),'units':str(units),'gross_usd':str(proceeds),'fee_usd':str(fee)}
    return None


def mark(state, price):
    equity=state['cash'] + state['units']*number(price)
    state['peak_equity']=max(state['peak_equity'],equity)
    dd = (state['peak_equity']-equity)/state['peak_equity']*100
    state['max_drawdown_pct']=max(state['max_drawdown_pct'],dd)
    state['exposure_bars']+=int(state['units']>0)
    state['bars']+=1
    return equity


def snapshot(state, price):
    equity=state['cash']+state['units']*number(price)
    wins=state['wins'];losses=state['losses']
    return {'equity_usd':round(float(equity),4), 'net_pnl_usd':round(float(equity-STARTING_CASH),4),
            'return_pct':round(float((equity/STARTING_CASH-1)*100),4),
            'max_drawdown_pct':round(float(state['max_drawdown_pct']),4),
            'fees_usd':round(float(state['fees']),4),
            'slippage_cost_usd':round(float(state['slippage_cost']),4),
            'turnover_usd':round(float(state['turnover_usd']),4),
            'trades':state['trades'], 'completed_round_trips':wins+losses,
            'win_rate_pct':round(100*wins/(wins+losses),2) if wins+losses else None,
            'exposure_pct':round(100*state['exposure_bars']/state['bars'],2) if state['bars'] else 0,
            'open_position':state['units']>0}


def test_segment(candles, strategy, begin, end):
    if begin < WARMUP or end>len(candles) or begin>=end:
        raise ValueError('invalid chronological segment')
    state=portfolio()
    for i in range(begin,end):
        # signal through i-1; next bar's OPEN is the earliest possible fill
        prior=candles[:i]
        # Do not use stale indicators across maintenance/no-trade gaps.
        # Require 48 contiguous preceding bars, including the execution hour.
        span=candles[max(0,i-48):i+1]
        continuous=all(span[j].timestamp_ms-span[j-1].timestamp_ms==HOUR_MS for j in range(1,len(span)))
        action=decision(strategy,prior,state['units']>0,state['entry_price']) if continuous else 'hold'
        execute(state,action,candles[i].open,prior[-1].volume)
        mark(state,candles[i].close)
    result=snapshot(state,candles[end-1].close)
    result.update({'strategy':strategy,'bars_evaluated':end-begin,'execution':'next_hour_open_simulated_taker',
                   'uses_future_information':False,'reported_pnl_is_real_money':False})
    return result


def buy_hold_segment(candles,begin,end):
    state=portfolio()
    execute(state,'buy',candles[begin].open,candles[begin-1].volume)
    for i in range(begin,end):mark(state,candles[i].close)
    return snapshot(state,candles[end-1].close)


def backtest(candles,symbol,history_days=90):
    if history_days < 90 or not candles:
        raise ValueError('at least 90 calendar days of prices required')
    expected=history_days*24
    observed_hours=(candles[-1].timestamp_ms-candles[0].timestamp_ms)//HOUR_MS+1
    if observed_hours != expected:
        raise ValueError('historical calendar window is incomplete')
    missing_hours=expected-len(candles)
    if missing_hours<0 or missing_hours>max(1,int(expected*.005)):
        raise ValueError('excessive missing historical hourly data')
    if any(candles[i].timestamp_ms<=candles[i-1].timestamp_ms for i in range(1,len(candles))):
        raise ValueError('nonchronological candles')
    holdout_start=candles[-1].timestamp_ms+HOUR_MS-30*24*HOUR_MS
    split=next((i for i,c in enumerate(candles) if c.timestamp_ms>=holdout_start),len(candles))
    if split < 50*24:
        raise ValueError('not enough training history')
    runs={}
    for strategy in ('momentum','grid'):
        runs[strategy]={'development':test_segment(candles,strategy,WARMUP,split),
                        'holdout':test_segment(candles,strategy,split,len(candles))}
    benchmark=buy_hold_segment(candles,split,len(candles))
    return {'symbol':symbol,'interval':'1h','bars':len(candles),
            'first_open_ms':candles[0].timestamp_ms,'last_closed_open_ms':candles[-1].timestamp_ms,
            'data_quality':{'observed_bars':len(candles),'expected_hours':expected,
                'missing_hours':missing_hours,'coverage_pct':round(100*len(candles)/expected,3),
                'missing_bars_imputed':0},
            'split':{'development_end_open_ms':candles[split-1].timestamp_ms,
                     'holdout_start_open_ms':candles[split].timestamp_ms,
                     'holdout_calendar_days':30,'development_calendar_days':history_days-30},
            'strategies':runs,'holdout_buy_hold_25pct_benchmark':benchmark,
            'assumed_taker_fee_rate':str(FEE_RATE),'adverse_slippage_rate':str(SLIPPAGE_RATE),
            'initial_cash_per_strategy_usd':str(STARTING_CASH),
            'model':'research_only_next_bar_open_fill_no_orderbook_queue_or_live_execution',
            'live_trades':0,'earnings_usd':0,'approved_for_live_trading':False}
