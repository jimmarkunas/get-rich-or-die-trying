import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from alpha.dex import factory_pool, scan_factories
from alpha.aave_discovery import borrower_addresses, scan_borrowers, BORROW_TOPIC
from alpha.scoreboard import summarize
from alpha.discovery import scan_exclusive_events

ADDR_A='0x'+'1'*40
ADDR_B='0x'+'2'*40
ADDR_C='0x'+'3'*40
FACTORY_1='0x'+'4'*40
FACTORY_2='0x'+'5'*40
POOL_1='0x'+'6'*40
POOL_2='0x'+'7'*40
RPC='https://rpc.example.org'


def market(e,letter,ask):
    return {'ticker':e+'-'+letter,'event_ticker':e,'market_type':'binary',
        'status':'active','settlement_bounds_type':'default',
        'rules_primary':'Ordinary verified binary winner pays one dollar.',
        'no_ask_dollars':ask,'liquidity_dollars':'10000'}


def event(e,ask):
    return {'event_ticker':e,'mutually_exclusive':True,
        'markets':[market(e,'A',ask),market(e,'B',ask)]}


def book(bid):
    return {'orderbook_fp':{'yes_dollars':[[bid,'50']],'no_dollars':[]}}


class KalshiSamplingTests(unittest.TestCase):
    @patch('alpha.discovery.fetch_book')
    @patch('alpha.discovery.fetch_event_pages')
    def test_economic_rank_beats_ticker_alphabet(self,fetch,books):
        fetch.return_value=[event('AA', '0.98'),event('ZZ','0.20')]
        books.return_value=book('0.95')
        obs,errs=scan_exclusive_events(max_events=1,max_pairs_per_event=1)
        self.assertFalse(errs)
        self.assertEqual(obs[0].details['event_ticker'],'ZZ')
        self.assertEqual(books.call_count,2)
    @patch('alpha.discovery.fetch_book')
    @patch('alpha.discovery.fetch_event_pages')
    def test_multiple_sizes_are_priced_from_orderbook_once(self,fetch,books):
        fetch.return_value=[event('EV','0.20')]
        books.return_value=book('0.95')
        rows,errs=scan_exclusive_events(quantities=[5,10,25],max_events=1)
        self.assertFalse(errs)
        self.assertEqual(len([r for r in rows if r.classification!='discovery_heartbeat']),3)
        self.assertEqual(books.call_count,2)
        self.assertEqual(rows[-1].details['priced_scenarios'],3)
    def test_unbounded_sizes_rejected(self):
        with self.assertRaises(ValueError):scan_exclusive_events(quantities=[1,2,3,4,5,6])


class DexDiscoveryTests(unittest.TestCase):
    @patch('alpha.dex.eth_call')
    def test_zero_pair_is_not_counted(self,call):
        call.return_value='0x'+'0'*64
        self.assertIsNone(factory_pool(RPC,FACTORY_1,ADDR_A,ADDR_B,'0xf'))
    @patch('alpha.dex.eth_call')
    def test_factory_returned_address_is_parsed(self,call):
        call.return_value='0x'+'0'*24+POOL_1[2:]
        self.assertEqual(factory_pool(RPC,FACTORY_1,ADDR_A,ADDR_B,'0xf').lower(),POOL_1.lower())
    @patch('alpha.dex.token_decimals',return_value=18)
    @patch('alpha.dex.pool_state')
    @patch('alpha.dex.factory_pool')
    @patch('alpha.dex.chain_block',return_value='0xa')
    def test_indicative_not_executable(self,chain,factory,state,decimals):
        factory.side_effect=[POOL_1,POOL_2]
        state.side_effect=[{'address':POOL_1,'token0':ADDR_A,'token1':ADDR_B,
            'reserve0':10**21,'reserve1':10**21},
            {'address':POOL_2,'token0':ADDR_A,'token1':ADDR_B,
            'reserve0':10**21,'reserve1':2*10**21}]
        rows,errs=scan_factories(RPC,8453,[FACTORY_1,FACTORY_2],
            [{'name':'A-B','token_a':ADDR_A,'token_b':ADDR_B}], [10**18],
            gas_cost_token0_base_units=10**12)
        self.assertFalse(errs)
        self.assertEqual(rows[0].classification,'indicative_positive_unverified')
        self.assertIsNone(rows[0].estimated_net_usd)
        self.assertFalse(rows[0].details['transaction_simulated'])
        self.assertTrue(rows[0].details['MEV_and_inclusion_unmodeled'])
    def test_duplicate_factory_rejected(self):
        with self.assertRaises(ValueError):scan_factories(RPC,8453,[FACTORY_1,FACTORY_1],
            [{'token_a':ADDR_A,'token_b':ADDR_B}],[10])


class AaveDiscoveryTests(unittest.TestCase):
    def test_debt_owner_topic_and_removed_logs(self):
        row={'address':POOL_1,'topics':[BORROW_TOPIC,'0x'+'0'*64,
             '0x'+'0'*24+ADDR_A[2:], '0x'+'0'*64]}
        self.assertEqual(borrower_addresses([row,{**row,'removed':True}],POOL_1),[ADDR_A.lower()])
    @patch('alpha.aave_discovery.account_data')
    @patch('alpha.aave_discovery.jsonrpc_call')
    @patch('alpha.aave_discovery.chain_block',return_value='0x2bc')
    def test_borrower_read_only_not_profit_claim(self,chain,rpc,account):
        rpc.return_value=[{'address':POOL_1,'topics':[BORROW_TOPIC,'0x'+'0'*64,
                          '0x'+'0'*24+ADDR_A[2:], '0x'+'0'*64]}]
        account.return_value={'health_factor':0.8,'debt_base_units':100,'collateral_base_units':90}
        rows,errors=scan_borrowers(RPC,POOL_1,1,lookback=100)
        self.assertFalse(errors)
        self.assertEqual(rows[0].classification,'health_below_one_profit_unknown')
        self.assertIsNone(rows[0].estimated_net_usd)
        self.assertTrue(rows[-1].details['sampled_only_not_exhaustive'])
        self.assertEqual(rpc.call_args.args[1],'eth_getLogs')
    def test_range_limit(self):
        with self.assertRaises(ValueError):scan_borrowers(RPC,POOL_1,1,lookback=3000)


class ScoreboardTests(unittest.TestCase):
    def test_profit_never_reported_as_realized(self):
        row={'engine':'kalshi','timestamp':'2026-10-16T10:00:00+00:00',
             'classification':'candidate_rule_review_required','estimated_net_usd':'20000'}
        r=summarize([row],days=7,now=datetime(2026,10,16,11,tzinfo=timezone.utc))
        self.assertEqual(r['engines']['kalshi']['best_indicative_net_usd'],'20000')
        self.assertIsNone(r['engines']['kalshi']['proven_realized_profit_usd'])
        self.assertTrue(r['real_profit_or_trade_fills_not_proven'])

if __name__=='__main__':unittest.main()
