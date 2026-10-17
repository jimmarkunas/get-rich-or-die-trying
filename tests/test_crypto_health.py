"""Tests use no network, credentials, or exchanges."""
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from alpha.crypto_health import HOUR_MS, SYMBOLS, analyze, main, transition

NOW = datetime(2026, 10, 17, 6, 30, tzinfo=timezone.utc)


def state_at(hours_before=2):
    stamp = int(NOW.timestamp()*1000)//HOUR_MS*HOUR_MS - hours_before*HOUR_MS
    return {'version': 1, 'symbols': {
        s: {'last_closed_open_ms': stamp, 'portfolios': {}} for s in SYMBOLS
    }}


class HealthTests(unittest.TestCase):
    def test_recent_closed_bar_healthy(self):
        result = analyze(state_at(2), NOW)
        self.assertEqual(result['status'], 'healthy')
        self.assertAlmostEqual(result['symbols']['BTCUSD']['lag_after_close_hours'], 1.5)

    def test_stale_even_when_workflow_passes(self):
        self.assertEqual(analyze(state_at(6), NOW)['status'], 'stale')

    def test_missing_state_fails_closed(self):
        self.assertEqual(analyze(None, NOW)['status'], 'invalid')

    def test_missing_symbol_fails_closed(self):
        state = state_at()
        del state['symbols']['SOLUSD']
        self.assertEqual(analyze(state, NOW)['status'], 'invalid')

    def test_impossible_future_bar_rejected(self):
        self.assertEqual(analyze(state_at(0), NOW)['status'], 'invalid')

    def test_unaligned_timestamp_rejected(self):
        state = state_at()
        state['symbols']['BTCUSD']['last_closed_open_ms'] += 1
        self.assertEqual(analyze(state, NOW)['status'], 'invalid')

    def test_timezone_awareness_required(self):
        with self.assertRaises(ValueError):
            analyze(state_at(), datetime(2026, 10, 17))

    def test_invalid_staleness_threshold(self):
        with self.assertRaises(ValueError):
            analyze(state_at(), NOW, 0.1)

    def test_stale_notice_is_deduplicated(self):
        stale = analyze(state_at(6), NOW)
        self.assertIn('STALE', transition(None, stale))
        self.assertIsNone(transition(stale, stale))

    def test_recovery_notice_only_on_transition(self):
        healthy = analyze(state_at(), NOW)
        stale = analyze(state_at(6), NOW)
        self.assertIsNone(transition(None, healthy))
        self.assertIn('RECOVERED', transition(stale, healthy))

    def test_cli_does_not_expose_portfolio_data(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root/'state.json').write_text(json.dumps(state_at(6)))
            code = main([
                '--state', str(root/'state.json'),
                '--previous-health', str(root/'old.json'),
                '--out', str(root/'new.json'),
                '--notice', str(root/'notice.md')
            ])
            self.assertEqual(code, 0)
            self.assertIn(json.loads((root/'new.json').read_text())['status'],
                          ('stale', 'invalid', 'healthy'))
            self.assertNotIn('portfolios', (root/'new.json').read_text())


if __name__ == '__main__':
    unittest.main()
