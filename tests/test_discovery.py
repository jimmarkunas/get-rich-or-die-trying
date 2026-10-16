import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from alpha.discovery import standard_binary_market, eligible_event, scan_exclusive_events, fetch_event_pages, metadata_digest
from alpha.archive import merge, alert_issue_payload
from datetime import datetime,timezone,timedelta


def market(ticker, ask='0.40', **kw):
    m={'ticker':ticker,'event_ticker':'EV-1','market_type':'binary','status':'active',
        'settlement_bounds_type':'default','rules_primary':'Winner is verified by an official source and receives $1.',
        'no_ask_dollars':ask}
    m.update(kw)
    return m


def event(**kw):
    e={'event_ticker':'EV-1','mutually_exclusive':True,'markets':[market('EV-1-A'),market('EV-1-B',ask='0.45')]}
    e.update(kw)
    return e


def book(yes, no):
    return {'orderbook_fp':{'yes_dollars':yes,'no_dollars':no}}


class AutoDiscoveryTests(unittest.TestCase):
    def test_no_assumption_of_yes_exhaustive(self):
        self.assertEqual(len(eligible_event(event())),2)
        self.assertEqual(eligible_event(event(mutually_exclusive=False)),[])
        self.assertEqual(eligible_event(event(mutually_exclusive=None)),[])
    def test_mismatched_ticker_is_rejected(self):
        self.assertFalse(standard_binary_market('EV-1',market('X',event_ticker='OTHER')))
    def test_special_settlements_fail_closed(self):
        for kw in ({'market_type':'scalar'},{'settlement_bounds_type':'custom'},
                   {'is_provisional':True},{'rules_primary':'Settlement may be a partial payout'},
                   {'rules_primary':''},{'status':'closed'}, {'settlement_floor_dollars':'0.5'}):
            with self.subTest(kw=kw):self.assertFalse(standard_binary_market('EV-1',market('EV-1-A',**kw)))
    def test_fee_override_skips_event(self):
        self.assertEqual(eligible_event(event(fee_type_override='some_other_scheme')),[])
    @patch('alpha.discovery.fetch_event_pages')
    @patch('alpha.discovery.fetch_book')
    def test_candidate_really_uses_books_not_metadata_asks(self,books,events):
        events.return_value=[event()]
        books.side_effect=[book([['0.88','25']], []), book([['0.88','25']], [])]
        rows,errors=scan_exclusive_events(quantity=10,buffer_usd='0.25')
        candidate=[r for r in rows if r.classification=='candidate_rule_review_required']
        self.assertEqual(len(candidate),1)
        self.assertEqual(Decimal(candidate[0].estimated_net_usd),Decimal('7.19')) # $2.40 cost + $0.16 rounded fees + $0.25 buffer
        self.assertEqual(candidate[0].details['conditional_payout_floor_usd'],'10')
        self.assertFalse(errors)
    @patch('alpha.discovery.fetch_event_pages')
    @patch('alpha.discovery.fetch_book')
    def test_no_liquidity_no_fake_profit(self,books,events):
        events.return_value=[event()]
        books.return_value=book([],[])
        rows,_=scan_exclusive_events(quantity=10)
        self.assertEqual(rows[0].classification,'insufficient_depth')
        self.assertIsNone(rows[0].estimated_net_usd)
    @patch('alpha.discovery.fetch_event_pages')
    @patch('alpha.discovery.fetch_book')
    def test_invalid_event_only_heartbeat(self,books,events):
        events.return_value=[event(mutually_exclusive=False)]
        rows,_=scan_exclusive_events()
        self.assertEqual([r.classification for r in rows],['discovery_heartbeat'])
        books.assert_not_called()
    @patch('alpha.discovery.request_json')
    def test_bounded_pagination(self,get):
        get.side_effect=[{'events':[event()],'cursor':'again'},{'events':[],'cursor':''}]
        self.assertEqual(len(fetch_event_pages(max_pages=2)),1)
        self.assertEqual(get.call_count,2)
    @patch('alpha.discovery.request_json')
    def test_repeated_cursor_throws(self,get):
        get.side_effect=[{'events':[],'cursor':'again'},{'events':[],'cursor':'again'}]
        with self.assertRaisesRegex(ValueError,'repeated'):
            fetch_event_pages()
    def test_digest_changes_on_changed_rules(self):
        a=event();b=event(markets=[market('EV-1-A',rules_primary='Something different'),market('EV-1-B')])
        self.assertNotEqual(metadata_digest(a,a['markets']),metadata_digest(b,b['markets']))

class DurableAlertTests(unittest.TestCase):
    def setUp(self):
        self.row={'engine':'kalshi','key':'EV-1:EV-1-A,EV-1-B','classification':'candidate_rule_review_required',
            'estimated_net_usd':'1.25','details':{'kind':'two_no_mutually_exclusive_lower_bound',
                'exchange_mutually_exclusive':True,'tickers':['EV-1-A','EV-1-B'],'event_ticker':'EV-1',
                'quantity':10,'metadata_sha256':'a'*64}}
        self.now=datetime(2026,10,16,tzinfo=timezone.utc)
    def test_deduplicate_alerts_across_runs(self):
        hist,state,alerts=merge([], [self.row],now=self.now)
        self.assertEqual(len(alerts),1)
        hist,state2,alerts2=merge(hist,[self.row],state,now=self.now+timedelta(hours=1))
        self.assertFalse(alerts2)
        self.assertEqual(len(hist),2)
        _,_,alerts3=merge(hist,[self.row],state2,now=self.now+timedelta(hours=25))
        self.assertEqual(len(alerts3),1)
    def test_no_signal_for_diagnostic_or_negative(self):
        row={**self.row,'classification':'no_positive_guarded_edge'}
        self.assertFalse(merge([], [row],now=self.now)[2])
        self.assertFalse(merge([], [{**self.row,'estimated_net_usd':'-1'}],now=self.now)[2])
        self.assertFalse(merge([], [{**self.row,'estimated_net_usd':'NaN'}],now=self.now)[2])
    def test_html_safety_of_issue(self):
        doc=alert_issue_payload([self.row],'https://example.com')
        self.assertIn('REVIEW REQUIRED',doc['title'])
        self.assertIn('not',doc['body'].lower())
        self.assertNotIn('private-key',doc['body'])
    def test_history_bounded(self):
        hist,_,_=merge([{'n':i} for i in range(40)],[],history_limit=3,now=self.now)
        self.assertEqual([x['n'] for x in hist],[37,38,39])

if __name__=='__main__':unittest.main()
