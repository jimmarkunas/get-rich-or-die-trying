"""Independent, fail-closed freshness monitor for paper trading research.

Reads only persisted state; no market calls, keys, orders, transactions, or funds.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

HOUR_MS = 3_600_000
SYMBOLS = ('BTCUSD', 'ETHUSD', 'SOLUSD')


def analyze(state, now, max_lag_hours=2.0):
    """Check the last processed CLOSED market bar, not workflow-success time."""
    if now.tzinfo is None:
        raise ValueError('now must be timezone-aware')
    if not (0.25 <= float(max_lag_hours) <= 24):
        raise ValueError('invalid lag threshold')
    now = now.astimezone(timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    latest_closed_open = (now_ms // HOUR_MS - 1) * HOUR_MS
    observed = {}
    if not isinstance(state, dict) or state.get('version') != 1 or not isinstance(state.get('symbols'), dict):
        return {'status': 'invalid', 'checked_at_utc': now.isoformat(), 'max_lag_hours': float(max_lag_hours),
                'symbols': {}, 'reason': 'missing or invalid paper state', 'live_trades': 0}
    healthy = True
    invalid = False
    for sym in SYMBOLS:
        item = state['symbols'].get(sym)
        if not isinstance(item, dict) or not isinstance(item.get('last_closed_open_ms'), int):
            observed[sym] = {'status': 'missing', 'reason': 'symbol has no processed closed bar'}
            invalid = True
            continue
        open_ms = item['last_closed_open_ms']
        if open_ms < 0 or open_ms % HOUR_MS or open_ms > latest_closed_open:
            observed[sym] = {'status': 'invalid', 'reason': 'processed bar timestamp impossible'}
            invalid = True
            continue
        lag = (now_ms - (open_ms + HOUR_MS)) / HOUR_MS
        status = 'stale' if lag > float(max_lag_hours) else 'healthy'
        observed[sym] = {
            'status': status,
            'closed_bar_open_utc': datetime.fromtimestamp(open_ms/1000, tz=timezone.utc).isoformat(),
            'lag_after_close_hours': round(lag, 3)
        }
        if status != 'healthy':
            healthy = False
    overall = 'invalid' if invalid else 'healthy' if healthy else 'stale'
    return {'status': overall, 'checked_at_utc': now.isoformat(), 'max_lag_hours': float(max_lag_hours),
            'symbols': observed, 'live_trades': 0,
            'reason': 'paper-state freshness, not profitability'}


def transition(previous, current):
    """Only report entering stale/invalid status and later recovery."""
    previous_status = previous.get('status') if isinstance(previous, dict) else None
    current_status = current['status']
    if current_status == previous_status:
        return None
    if current_status in ('stale', 'invalid'):
        lines = [
            '**Automated Alpha paper health: ' + current_status.upper() + '**',
            'Checked: ' + current['checked_at_utc'],
            'Only research monitoring is affected; no real-money trading exists.',
            'Workflow: https://github.com/jimmarkunas/get-rich-or-die-trying/actions/workflows/crypto-paper.yml',
            'Never reconstruct missing fills.'
        ]
        for sym, info in current.get('symbols', {}).items():
            lines.append('- ' + sym + ': ' + str(info.get('status')) +
                         '; hours after bar close: ' + str(info.get('lag_after_close_hours', 'n/a')))
        return '\n'.join(lines)
    if current_status == 'healthy' and previous_status in ('stale', 'invalid'):
        return ('**Automated Alpha paper health: RECOVERED** at ' + current['checked_at_utc'] +
                '. The latest closed bars are current. Missed fills remain missing, not simulated retroactively.')
    return None


def read_json(path):
    p = Path(path)
    if not p.is_file() or p.stat().st_size == 0:
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None


def main(argv=None):
    p = argparse.ArgumentParser(description='Read-only crypto paper freshness monitor')
    p.add_argument('--state', required=True)
    p.add_argument('--previous-health', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--notice', required=True)
    p.add_argument('--max-lag-hours', type=float, default=2.0)
    args = p.parse_args(argv)
    previous = read_json(args.previous_health)
    result = analyze(read_json(args.state), datetime.now(timezone.utc), args.max_lag_hours)
    msg = transition(previous, result)
    for fname in (args.out, args.notice):
        Path(fname).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    Path(args.notice).write_text((msg + '\n') if msg else '', encoding='utf-8')
    print(json.dumps({'health': result['status'], 'alert_transition': bool(msg), 'paper_only': True}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
