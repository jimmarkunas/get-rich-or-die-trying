import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from decimal import Decimal
from alpha.incentive_research import (active_incentives, parse_book, hypothetical_quote,
    analyze_program, scan, cli)

NOW=datetime(2026,10,17,10,0,tzinfo=timezone.utc)

def example(ticker='KXFOO-BAR', ident='p1'):
    return {'id':ident,'market_ticker':ticker,'incentive_type':'liquidity',
            'period_reward':100000,'discount_factor_bps':9000,'target_size_fp':'150.00',
            'start_date':'2026-10-16T00:00:00Z','end_date':'2026-10-18T00:00:00Z'}

def book(yes='250',no='250'):
    return {'orderbook_fp':{'yes_dollars':[['0.45',yes]],'no_dollars':[['0.50',no]]}}

class IncentiveTests(unittest.TestCase):
    def test_active_list_and_pagination(self):
        calls=[]
        def get(u,params):
            calls.append(params)
            return {'incentive_programs':[example()], 'next_cursor':'next'} if len(calls)==1 else {'incentive_programs':[example(ident='p2')], 'next_cursor':None}
        xs,m=active_incentives(now=NOW,getter=get)
        self.assertEqual(len(xs),2)
        self.assertEqual(calls[1]['cursor'],'next')
        self.assertFalse(m['truncated_pagination'])
    def test_date_boundary(self):
        def get(u,params):return {'incentive_programs':[dict(example(), end_date='2026-10-17T10:00:00Z')], 'next_cursor':None}
        xs,_=active_incentives(now=NOW,getter=get)
        self.assertEqual(xs,[])
    def test_type_filter_no_volume_rewards(self):
        def get(u,params):return {'incentive_programs':[dict(example(),incentive_type='volume')], 'next_cursor':None}
        xs,_=active_incentives(now=NOW,getter=get)
        self.assertEqual(xs,[])
    def test_schema_change_fails(self):
        with self.assertRaises(ValueError):active_incentives(now=NOW,getter=lambda u,params:{})
    def test_duplicate_cursor_fails(self):
        with self.assertRaises(ValueError):active_incentives(now=NOW,getter=lambda u,params:{'incentive_programs':[],'next_cursor':'same'})
    def test_limits(self):
        with self.assertRaises(ValueError):active_incentives(pages=11)
        with self.assertRaises(ValueError):scan(max_books=500)
    def test_bad_program_skips(self):
        def get(u,params):return {'incentive_programs':[dict(example(),period_reward='NaN'),example(ident='p2')], 'next_cursor':None}
        xs,_=active_incentives(now=NOW,getter=get)
        self.assertEqual(len(xs),1)
    def test_bad_market_ticker_skips(self):
        def get(u,params):return {'incentive_programs':[example(ticker='bad/path')], 'next_cursor':None}
        xs,_=active_incentives(now=NOW,getter=get)
        self.assertEqual(xs,[])
    def test_parse_both_sides(self):
        self.assertEqual(parse_book(book())['yes'][0],(Decimal('.45'),Decimal('250')))
    def test_bad_orderbook_fails(self):
        with self.assertRaises(ValueError):parse_book({'orderbook_fp':{'yes_dollars':[]}})
    def test_target_met(self):
        p=analyze_program(example(),book())
        self.assertTrue(p['book']['both_sides_already_reach_target'])
        self.assertEqual(p['simulated_yes_bid']['status'],'visible_book_meets_depth_gate_personal_qualification_unknown')
        self.assertEqual(p['simulated_yes_bid']['hypothetical_contracts'],50)
        self.assertEqual(p['simulated_yes_bid']['max_cash_committed_if_posted_usd'],'22.50')
    def test_missing_opposite_depth_no_qualification(self):
        p=analyze_program(example(),book(no='0'))
        self.assertEqual(p['simulated_yes_bid']['status'],'no_two_sided_quotes')
        self.assertIsNone(p['hypothetical_payout_usd'])
    def test_insufficient_depth(self):
        p=analyze_program(example(),book(yes='30',no='70'))
        self.assertEqual(p['simulated_yes_bid']['status'],'insufficient_two_sided_target_depth')
    def test_no_reward_prediction(self):
        p=analyze_program(example(),book())
        self.assertFalse(p['reward_currency_unit_verified'])
        self.assertIsNone(p['expected_trading_net_usd'])
        self.assertEqual(p['actual_payout_usd'],0)
    def test_budget_restricts_quantity(self):
        p=analyze_program(example(),book(),budget='10')
        self.assertEqual(p['simulated_yes_bid']['hypothetical_contracts'],22)
        self.assertLessEqual(Decimal(p['simulated_yes_bid']['max_cash_committed_if_posted_usd']),10)
    def test_crossed_book_rejected(self):
        q=hypothetical_quote([(Decimal('.6'),Decimal(200))],[(Decimal('.5'),Decimal(200))],Decimal(100),Decimal(100),50)
        self.assertEqual(q['status'],'crossed_or_locked_quotes')
    def test_scan_reads_book_once_for_multiple_incentives(self):
        paths=[]
        def get(url,params=None):
            paths.append(url)
            if url.endswith('/incentive_programs'):return {'incentive_programs':[example(),example(ident='p2')],'next_cursor':None}
            return book()
        o=scan(getter=get,now=NOW)
        self.assertEqual(o['programs_analyzed'],2)
        self.assertEqual(len(paths),2)
        self.assertEqual(o['actual_rewards_earned_usd'],0)
        self.assertEqual(o['feasible_visible_joins'],4)
    def test_partial_book_failure_is_reported(self):
        def get(url,params=None):
            if url.endswith('/incentive_programs'):
                return {'incentive_programs':[example(),example(ticker='KXBAR-BAZ',ident='p2')],'next_cursor':None}
            if url.endswith('KXFOO-BAR/orderbook'):raise ConnectionError('blocked')
            return book()
        o=scan(getter=get,now=NOW)
        self.assertEqual(len(o['errors']),1)
        self.assertEqual(o['programs_analyzed'],1)
    def test_pagination_cap_surfaced(self):
        def get(url,params):return {'incentive_programs':[example()], 'next_cursor':'a' if 'cursor' not in params else 'b'}
        _,meta=active_incentives(pages=1,getter=get,now=NOW)
        self.assertTrue(meta['truncated_pagination'])
    def test_rotation_covers_different_markets_without_losing_anchor(self):
        programs=[example(ticker=f'KXTEST-{i:03}',ident=f'id-{i}') for i in range(10)]
        def get(url,params=None):
            if url.endswith('/incentive_programs'):return {'incentive_programs':programs,'next_cursor':None}
            return book()
        a=scan(getter=get,now=NOW,max_books=5)
        b=scan(getter=get,now=NOW+timedelta(hours=6),max_books=5)
        aa={x['market_ticker'] for x in a['samples']}
        bb={x['market_ticker'] for x in b['samples']}
        self.assertEqual(len(aa),5)
        self.assertEqual(len(bb),5)
        self.assertEqual(len(aa & bb),4)
        self.assertEqual(a['sampling']['fixed_anchor_count'],4)
        self.assertEqual(a['sampling']['rotating_count'],1)

    def test_period_reward_never_formatted_as_dollars(self):
        o=analyze_program(example(),book())
        self.assertNotIn('daily_revenue_usd',o)
        self.assertEqual(o['period_reward_api_raw'],'100000')
    def test_zero_program_response_is_not_a_profit(self):
        o=scan(getter=lambda url,params=None:{'incentive_programs':[],'next_cursor':None},now=NOW)
        self.assertEqual(o['programs_available'],0)
        self.assertEqual(o['actual_rewards_earned_usd'],0)

if __name__=='__main__':unittest.main()
