import json
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch

from alpha.crypto_data import (Candle, HOUR_MS, SYMBOLS, parse_candle, fetch_candles,
                               fetch_book_ticker, public_get, validate_candles)
from alpha.crypto_strategy import (backtest, decision, execute, mark, portfolio,
                                   snapshot, test_segment)
from alpha.crypto_forward import create_state, paper_cycle, serialize, deserialize


def fake_candles(n=2160, start=1_700_000_000_000//HOUR_MS*HOUR_MS):
    bars=[]
    for i in range(n):
        # Long, oscillating series with time-varying momentum and occasional declines.
        close = Decimal(100)+(Decimal(i%144-72)*Decimal('.2')) + Decimal(i//168)*Decimal('.07')
        op = close * Decimal('.9995')
        bars.append(Candle(start+i*HOUR_MS,op,close*Decimal('1.001'),op*Decimal('.999'),close,Decimal('100000')))
    return bars


def raw(bar):
    return [bar.timestamp_ms,str(bar.open),str(bar.high),str(bar.low),str(bar.close),str(bar.volume),
            bar.timestamp_ms+HOUR_MS-1,'ignored',1,'ignored','ignored','0']


class TestCryptoData(TestCase):
    def test_parse_valid_ohlc(self):
        b=fake_candles(1)[0]
        self.assertEqual(parse_candle(raw(b)),b)

    def test_incomplete_ohlc_invalid(self):
        b=raw(fake_candles(1)[0]);b[6]=b[0]-1
        with self.assertRaises(ValueError):parse_candle(b)

    def test_non_finite_price_rejected(self):
        b=raw(fake_candles(1)[0]);b[4]='NaN'
        with self.assertRaises(ValueError):parse_candle(b)

    def test_missing_hours_rejected(self):
        candles=fake_candles(3)
        with self.assertRaisesRegex(ValueError,'missing'):
            validate_candles([candles[0],candles[2]])

    @patch('alpha.crypto_data.public_get')
    def test_paginated_exact_90_day_dataset(self, get):
        bars=fake_candles(2160)
        now=bars[-1].timestamp_ms+HOUR_MS+40_000
        def endpoint(path,params):
            start=params['startTime']; limit=params['limit']
            choices=[raw(b) for b in bars if start<=b.timestamp_ms<now//HOUR_MS*HOUR_MS]
            return choices[:limit]
        get.side_effect=endpoint
        result=fetch_candles('BTCUSD',2160,now_ms=now)
        self.assertEqual(result,bars)
        self.assertEqual(get.call_count,3)

    @patch('alpha.crypto_data.public_get')
    def test_no_partial_incomplete_dataset_allowed(self,get):
        get.return_value=[]
        with self.assertRaises(ValueError):fetch_candles('ETHUSD',2160,now_ms=1_720_000_000_000)

    def test_no_unsupported_symbol(self):
        with self.assertRaises(ValueError):fetch_candles('DOGEUSDT',2160)

    @patch('alpha.crypto_data.public_get')
    def test_bid_ask_quantity_validation(self,get):
        get.return_value={'symbol':'SOLUSD','bidPrice':'99','askPrice':'100',
                          'bidQty':'1','askQty':'2'}
        t=fetch_book_ticker('SOLUSD')
        self.assertEqual(t['bid'],Decimal(99))
        get.return_value['bidPrice']='101'
        with self.assertRaises(ValueError):fetch_book_ticker('SOLUSD')

    def test_api_does_not_allow_orders(self):
        with self.assertRaisesRegex(ValueError,'allowlist'):
            public_get('/api/v3/order',{})


class TestCryptoStrategies(TestCase):
    def test_independent_30_day_holdout(self):
        candles=fake_candles()
        result=backtest(candles,'BTCUSD')
        self.assertEqual(result['split']['holdout_calendar_days'],30)
        self.assertEqual(result['bars'],2160)
        for s in ('momentum','grid'):
            self.assertEqual(result['strategies'][s]['holdout']['bars_evaluated'],720)
            self.assertEqual(result['strategies'][s]['holdout']['execution'],'next_hour_open_simulated_taker')
        self.assertFalse(result['approved_for_live_trading'])
        self.assertEqual(result['earnings_usd'],0)

    def test_requires_90days(self):
        with self.assertRaises(ValueError):backtest(fake_candles(800),'BTCUSD')

    def test_lookahead_free_signal(self):
        prior=fake_candles(100)
        # A subsequent bar (not in prior) must not affect decision.
        before=decision('momentum',prior,False)
        after=decision('momentum',prior,False)
        self.assertEqual(before,after)

    def test_trade_spends_no_more_than_cash(self):
        s=portfolio();f=execute(s,'buy',Decimal(100),Decimal(500))
        self.assertIsNotNone(f)
        self.assertGreater(s['cash'],0)
        self.assertLessEqual(s['units']*Decimal(100),Decimal(251))
        self.assertGreater(s['fees'],0)
        execute(s,'sell',Decimal(101),Decimal(500))
        self.assertEqual(s['units'],0)
        self.assertEqual(s['trades'],2)

    def test_zero_volume_refuses_fill(self):
        s=portfolio()
        self.assertIsNone(execute(s,'buy',Decimal(100),Decimal(0)))
        self.assertEqual(s['trades'],0)

    def test_bid_size_blocks_paper_sale(self):
        s=portfolio();execute(s,'buy',Decimal(100),Decimal(200))
        self.assertIsNone(execute(s,'sell',Decimal(99),Decimal(200),max_units='0.00001'))
        self.assertGreater(s['units'],0)

    def test_no_future_bar_access_for_segment(self):
        bars=fake_candles(300)
        x=test_segment(bars,'grid',55,100)
        # Changing every bar after the evaluation period cannot affect result.
        altered=bars[:100]+[Candle(t.timestamp_ms,t.open,t.high,t.low,t.close*100,t.volume) for t in bars[100:]]
        y=test_segment(altered,'grid',55,100)
        self.assertEqual(x,y)

    def test_mark_to_market_and_drawdown(self):
        s=portfolio();execute(s,'buy',Decimal(100),Decimal(500))
        mark(s,Decimal(120));mark(s,Decimal(70))
        self.assertGreater(snapshot(s,Decimal(70))['max_drawdown_pct'],0)


class TestForwardPaper(TestCase):
    def reader(self,symbol,hours):
        self.assertEqual(hours,120)
        return fake_candles(120,start=self.start)

    def quotes(self,symbol):
        return {'bid':Decimal(99),'ask':Decimal(100),'bid_qty':Decimal(100),
                'ask_qty':Decimal(100),'observed_at_utc':'2026-10-16T00:00:00Z'}

    def setUp(self):
        self.start=fake_candles(1)[0].timestamp_ms

    def test_cold_start_never_fills_historical_signals(self):
        state,log=paper_cycle(create_state(),symbols=('BTCUSD',),
                              candle_reader=self.reader,quote_reader=self.quotes)
        self.assertEqual(log[0]['status'],'seeded_no_backdated_trades')
        self.assertEqual(log[0]['paper_trades'],0)
        self.assertEqual(deserialize(state['symbols']['BTCUSD']['portfolios']['momentum'])['cash'],1000)

    def test_idempotent_same_candle(self):
        state,_=paper_cycle(create_state(),symbols=('BTCUSD',),
                             candle_reader=self.reader,quote_reader=self.quotes)
        newer,log=paper_cycle(state,symbols=('BTCUSD',),
                              candle_reader=self.reader,quote_reader=self.quotes)
        self.assertEqual(newer,state)
        self.assertEqual(log[0]['status'],'already_processed')

    def test_next_candle_is_paper_evaluated(self):
        old,_=paper_cycle(create_state(),symbols=('BTCUSD',),
                           candle_reader=self.reader,quote_reader=self.quotes)
        self.start+=HOUR_MS
        updated,log=paper_cycle(old,symbols=('BTCUSD',),
                                 candle_reader=self.reader,quote_reader=self.quotes)
        self.assertEqual(len(log),2)
        self.assertTrue(all(x['status']=='paper_evaluated' for x in log))
        self.assertEqual(updated['symbols']['BTCUSD']['last_closed_open_ms'],self.start+119*HOUR_MS)

    def test_stale_gap_no_retroactive_fills(self):
        old,_=paper_cycle(create_state(),symbols=('BTCUSD',),
                          candle_reader=self.reader,quote_reader=self.quotes)
        self.start+=4*HOUR_MS
        _,log=paper_cycle(old,symbols=('BTCUSD',),
                          candle_reader=self.reader,quote_reader=self.quotes)
        self.assertEqual({x['status'] for x in log},{'stale_gap_skipped'})
        self.assertFalse(any(x['simulated_fill'] for x in log))

    def test_serialized_state_round_trip(self):
        old=portfolio();execute(old,'buy',Decimal(100),Decimal(100))
        self.assertEqual(deserialize(json.loads(json.dumps(serialize(old)))),old)

    def test_bad_state_rejected(self):
        with self.assertRaises(ValueError):paper_cycle({'version':72,'symbols':{}},
                             candle_reader=self.reader,quote_reader=self.quotes)

if __name__=='__main__':
    import unittest
    unittest.main()

class TestCryptoDashboard(TestCase):
    def test_empty_dashboard_is_valid_static_html(self):
        from alpha.crypto_dashboard import render
        page=render(None,create_state())
        self.assertIn('<!DOCTYPE html>',page)
        self.assertIn('No live trades',page)

    def test_dynamic_strings_are_escaped(self):
        from alpha.crypto_dashboard import render
        page=render({'studies':[{'symbol':'<script>alert(1)</script>',
             'strategies':{s:{'development':{'net_pnl_usd':0},'holdout':{
                 'net_pnl_usd':0,'return_pct':0,'max_drawdown_pct':0,'trades':0}} for s in ('momentum','grid')},
             'holdout_buy_hold_25pct_benchmark':{'net_pnl_usd':0}}]},create_state())
        self.assertNotIn('<script>',page)
        self.assertIn('&lt;script&gt;',page)

class TestNoFutureVolume(TestCase):
    def test_next_bar_unknown_volume_cannot_change_fill(self):
        a=fake_candles(130)
        b=list(a)
        # For any strategy, the volume INSIDE the bar being executed is unknowable
        # at its opening; changing it cannot change historical simulated orders.
        b[100]=Candle(a[100].timestamp_ms,a[100].open,a[100].high,a[100].low,
                      a[100].close,Decimal('0'))
        for strat in ('momentum','grid'):
            self.assertEqual(test_segment(a,strat,90,101),test_segment(b,strat,90,101))

class TestPaperCliStateBootstrapping(TestCase):
    def test_empty_git_show_redirect_treated_as_new_state(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from alpha.crypto_cli import main
        with tempfile.TemporaryDirectory() as d:
            previous=Path(d)/'missing_previous_is_empty.json'
            previous.write_text('')
            with patch('alpha.crypto_cli.paper_cycle',return_value=(create_state(),[])) as run:
                code=main(['forward','--symbols','BTCUSD','--state-in',str(previous),
                           '--state-out',str(Path(d)/'new.json'),
                           '--observations',str(Path(d)/'observations.jsonl')])
            self.assertEqual(code,0)
            self.assertIsNone(run.call_args.args[0])

class TestHourlyCloseTimestampVariants(TestCase):
    def test_close_time_can_be_exclusive_end_timestamp(self):
        row=raw(fake_candles(1)[0]);row[6]=row[0]+HOUR_MS
        self.assertEqual(parse_candle(row).timestamp_ms,row[0])

    def test_close_time_cannot_refer_to_distant_future(self):
        row=raw(fake_candles(1)[0]);row[6]=row[0]+24*HOUR_MS
        with self.assertRaisesRegex(ValueError,'delta_ms='):
            parse_candle(row)

class TestRealExchangeGaps(TestCase):
    def test_9_missing_hours_do_not_get_synthetic_fills(self):
        raw_bars=fake_candles(2160)
        gap=set(range(340,349))
        bars=[c for i,c in enumerate(raw_bars) if i not in gap]
        self.assertEqual(len(bars),2151)
        self.assertEqual(len(validate_candles(bars,min_count=2150,max_missing_hours=10)),2151)
        report=backtest(bars,'BTCUSD')
        self.assertEqual(report['data_quality']['missing_hours'],9)
        self.assertEqual(report['data_quality']['missing_bars_imputed'],0)
        self.assertEqual(report['split']['holdout_calendar_days'],30)
        self.assertEqual(report['strategies']['momentum']['holdout']['bars_evaluated'],720)

    def test_large_gap_refused(self):
        bars=fake_candles(2160)
        with self.assertRaises(ValueError):validate_candles(bars[:20]+bars[50:],min_count=1,max_missing_hours=10)

    @patch('alpha.crypto_data.public_get')
    def test_api_pagination_with_gaps(self, get):
        bars=fake_candles(2160)
        bars=[bar for i,bar in enumerate(bars) if i not in set(range(800,809))]
        cutoff=bars[-1].timestamp_ms+HOUR_MS
        def endpoint(path,params):
            options=[raw(b) for b in bars if params['startTime']<=b.timestamp_ms<cutoff]
            return options[:params['limit']]
        get.side_effect=endpoint
        received=fetch_candles('BTCUSD',2160,now_ms=cutoff)
        self.assertEqual(received,bars)
        self.assertEqual(len(received),2151)

class TestForwardGapSafety(TestCase):
    def test_no_forward_fill_when_recent_history_has_hole(self):
        bars=fake_candles(120)
        state=create_state()
        def initial(symbol,n):return bars
        quote=lambda symbol:{'bid':Decimal(99),'ask':Decimal(100),'bid_qty':Decimal(100),'ask_qty':Decimal(100)}
        state,_=paper_cycle(state,symbols=('ETHUSD',),candle_reader=initial,quote_reader=quote)
        nextbars=fake_candles(121)[1:]
        # A hole 20 bars back prevents using indicators over a discontinuity.
        nextbars=nextbars[:99]+nextbars[100:]
        state,logs=paper_cycle(state,symbols=('ETHUSD',),candle_reader=lambda s,n:nextbars,quote_reader=quote)
        self.assertEqual({x['status'] for x in logs},{'stale_gap_skipped'})
        self.assertFalse(any(x.get('simulated_fill') for x in logs))
