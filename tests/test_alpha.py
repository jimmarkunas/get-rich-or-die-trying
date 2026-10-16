import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from alpha.common import Observation, jsonrpc_call, words, write_observations
from alpha.kalshi import ask_levels, basket_quote, fee, parse_bids, quote_purchase, scan_kalshi
from alpha.defi import account_data, amm_out, pool_state, roundtrip, scan_aave, scan_flash_amm
from alpha.report import render_report


def book(yes, no):
    return {'orderbook_fp':{'yes_dollars':yes,'no_dollars':no}}

class KalshiTests(unittest.TestCase):
    def test_inverse_order_book(self):
        b=book([['0.36','7'],['0.30','8']],[['0.45','12'],['0.40','2']])
        self.assertEqual(ask_levels(b,'yes')[0],(Decimal('0.55'),12))
        self.assertEqual(ask_levels(b,'no')[0],(Decimal('0.64'),7))

    def test_executable_depth_and_cost(self):
        b=book([['0.35','15']],[['0.48','2'],['0.40','4']])
        q=quote_purchase(b,'yes',5)
        self.assertEqual(q['cost'],Decimal('2.84'))  # 2*.52 + 3*.60
        self.assertEqual(q['contracts'],5)
        self.assertIsNone(quote_purchase(b,'yes',7))

    def test_fee_rounds_up(self):
        self.assertEqual(fee('0.50',1),Decimal('0.02'))
        self.assertEqual(fee('0.50',100),Decimal('1.75'))
        with self.assertRaises(ValueError):fee('-0.1',1)

    def test_reject_new_schema_gap(self):
        with self.assertRaises(ValueError):quote_purchase({},'yes',10)

    def test_fractional_size_not_tradable(self):
        self.assertIsNone(quote_purchase(book([], [['0.4','0.99']]),'yes',1))

    def test_cross_market_needs_verified_partition(self):
        a=book([], [['0.80','10']]) # ask YES .20
        b=book([], [['0.78','10']]) # ask YES .22
        with patch('alpha.kalshi.fetch_markets',return_value=[]), patch('alpha.kalshi.fetch_book',side_effect=[a,b]):
            result,errors=scan_kalshi(tickers=['A','B'],groups=[{'name':'example', 'payout_partition_verified':False,
                 'legs':[{'ticker':'A','side':'yes'},{'ticker':'B','side':'yes'}]}],quantity=5,buffer_usd='0.25')
        g=[r for r in result if r.key=='example'][0]
        self.assertEqual(g.classification,'unverified_payout_partition')
        self.assertGreater(Decimal(g.estimated_net_usd),0)
        self.assertFalse(errors)

    def test_validated_partition_still_manual(self):
        a=book([], [['0.80','10']]);b=book([], [['0.78','10']])
        with patch('alpha.kalshi.fetch_markets',return_value=[]),patch('alpha.kalshi.fetch_book',side_effect=[a,b]):
            r,_=scan_kalshi(tickers=['A','B'],groups=[{'name':'test','payout_partition_verified':True,
               'legs':[{'ticker':'A','side':'yes'},{'ticker':'B','side':'yes'}]}],quantity=5)
        self.assertEqual([o for o in r if o.key=='test'][0].classification,'candidate_manual_execution_risk')

    def test_empty_series_is_observable_not_a_trade(self):
        with patch('alpha.kalshi.fetch_markets', return_value=[]):
            observations, errors = scan_kalshi(series='KXHIGHNY', quantity=3)
        self.assertEqual(errors, {})
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].classification,
                         'no_open_markets_in_configured_series')
        self.assertIsNone(observations[0].estimated_net_usd)

    def test_missing_liquidity_does_not_create_profit(self):
        q=basket_quote([{'ticker':'A','side':'yes'},{'ticker':'B','side':'yes'}],{'A':book([],[]),'B':book([],[])},2)
        self.assertIsNone(q)

    def test_duplicate_leg_rejected(self):
        with self.assertRaises(ValueError):
            basket_quote([{'ticker':'A','side':'yes'}]*2,{},2)

class DeFiTests(unittest.TestCase):
    def test_abi_words(self):
        b='0x'+''.join(f'{x:064x}' for x in [1,2,3])
        self.assertEqual(words(b,3),[1,2,3])
        with self.assertRaises(ValueError):words('0x12',3)

    @patch('alpha.defi.eth_call')
    def test_user_account_health_factor(self,mock_call):
        mock_call.return_value='0x'+''.join(f'{x:064x}' for x in [100,70,0,8000,7000,900000000000000000])
        user='0x'+'1'*40
        result=account_data('https://rpc.test','0x'+'2'*40,user,'0x10')
        self.assertEqual(result['health_factor'],Decimal('0.9'))
        self.assertEqual(result['debt_base_units'],70)
        self.assertIn(user[2:].lower(),mock_call.call_args.args[2])

    @patch('alpha.defi.chain_block',return_value='0xa')
    @patch('alpha.defi.account_data')
    def test_liquidation_health_not_profit(self,getdata,block):
        getdata.return_value={'user':'0x'+'1'*40,'health_factor':Decimal('0.95'),
                   'collateral_base_units':500,'debt_base_units':200,
                   'ltv_bps':7000,'liquidation_threshold_bps':8000}
        rows=scan_aave('https://rpc.example',['0x'+'1'*40])
        self.assertEqual(rows[0].classification,'potential_liquidation_health_only')
        self.assertIsNone(rows[0].estimated_net_usd)

    def test_amm_math_reduces_output_with_fee(self):
        self.assertLess(amm_out(1000,10000,10000,30),amm_out(1000,10000,10000,0))
        self.assertEqual(amm_out(1000,10000,10000,30),906)

    def test_roundtrip_equivalent_pools_loses_fees(self):
        p={'reserve0':100_000_000,'reserve1':100_000_000}
        self.assertLess(roundtrip(10_000,p,p,30,30),10_000)

    @patch('alpha.defi.chain_block',return_value='0x123')
    @patch('alpha.defi.pool_state')
    def test_reject_mismatched_pair(self,state,block):
        p={'address':'0x'+'1'*40,'token0':'0x'+'3'*40,'token1':'0x'+'4'*40,'reserve0':1000,'reserve1':1000}
        q={**p,'token1':'0x'+'5'*40}
        state.side_effect=[p,q]
        with self.assertRaisesRegex(ValueError,'mismatched'):
            scan_flash_amm('https://rpc.test',[{'pool_a':'0x'+'1'*40,'pool_b':'0x'+'2'*40,
              'amount_token0_base_units':'100','flash_loan_premium_bps_assumption':5,
              'gas_cost_token0_base_units_assumption':'10','pool_a_fee_bps':30,'pool_b_fee_bps':30}])

    @patch('alpha.defi.chain_block',return_value='0x123')
    @patch('alpha.defi.pool_state')
    def test_positive_flash_still_indicative(self,state,block):
        p={'address':'0x'+'1'*40,'token0':'0x'+'3'*40,'token1':'0x'+'4'*40,'reserve0':100_000,'reserve1':200_000}
        q={**p,'address':'0x'+'2'*40,'reserve0':200_000,'reserve1':100_000}
        state.side_effect=[p,q]
        result=scan_flash_amm('https://rpc.test',[{'pool_a':p['address'],'pool_b':q['address'],
              'amount_token0_base_units':'1000','flash_loan_premium_bps_assumption':5,
              'gas_cost_token0_base_units_assumption':'10','pool_a_fee_bps':30,'pool_b_fee_bps':30}])
        self.assertEqual(result[0].classification,'indicative_positive_not_executable')
        self.assertIsNone(result[0].estimated_net_usd)
        self.assertFalse(result[0].details['is_executable_quote'])

class StorageAndSafetyTests(unittest.TestCase):
    def test_rpc_write_methods_blocked(self):
        for method in ['eth_sendRawTransaction','eth_sendTransaction','personal_sign','eth_estimateGas']:
            with self.assertRaises(ValueError):jsonrpc_call('https://rpc.test',method,[])

    def test_rpc_no_http(self):
        with self.assertRaises(ValueError):jsonrpc_call('http://rpc.test','eth_blockNumber',[])

    def test_html_report_escapes_content(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'ledger.jsonl';out=Path(d)/'index.html'
            x=Observation('kalshi','<img src=x onerror=1>', '2026-10-16T00:00:00Z','diagnostic',None,{},'fixture')
            write_observations(path,[x]);num=render_report(path,out)
            self.assertEqual(num,1)
            content=out.read_text()
            self.assertIn('&lt;img',content)
            self.assertNotIn('<img src=x',content)

if __name__=='__main__':unittest.main()
