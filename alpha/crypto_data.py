"""Binance.US public OHLCV and quote reader; no authentication or order endpoints.

Data integrity is fail-closed. Only COMPLETED hourly bars are included.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import re
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = 'https://api.binance.us'
SYMBOLS = ('BTCUSD', 'ETHUSD', 'SOLUSD')
HOUR_MS = 3_600_000


@dataclass(frozen=True)
class Candle:
    timestamp_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


def number(value):
    try:
        val = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError('invalid decimal') from exc
    if not val.is_finite():
        raise ValueError('non-finite market datum')
    return val


def public_get(path, params, timeout=12):
    if path not in ('/api/v3/klines', '/api/v3/ticker/bookTicker'):
        raise ValueError('public API allowlist violation')
    url = BASE + path + '?' + urlencode(params)
    request = Request(url, headers={'User-Agent': 'AutomatedAlpha-Research/0.5', 'Accept': 'application/json'})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError('public API returned non-200')
        body = response.read(1_500_001)
    if len(body) > 1_500_000:
        raise ValueError('public API response exceeds size cap')
    return json.loads(body)


def parse_candle(row):
    if not isinstance(row, list) or len(row) < 7:
        raise ValueError('invalid Kline schema')
    ts = int(row[0])
    if ts % HOUR_MS != 0:
        raise ValueError('Kline timestamp is not aligned to UTC hour')
    opening, high, low, close, volume = map(number, row[1:6])
    if min(opening, high, low, close) <= 0 or volume < 0:
        raise ValueError('non-positive price or negative volume')
    if high < max(opening, close) or low > min(opening, close):
        raise ValueError('inconsistent OHLC')
    # Do not hard-code inclusive-vs-exclusive close-time conventions: the
    # authoritative completeness check is the requested UTC cutoff and
    # verified sequence of hourly OPEN timestamps in fetch_candles().
    # Still reject malformed or wildly out-of-interval close metadata.
    close_time = int(row[6])
    if not ts <= close_time <= ts + HOUR_MS:
        raise ValueError(f'invalid Kline close_time delta_ms={close_time-ts}')
    return Candle(ts, opening, high, low, close, volume)


def validate_candles(candles, min_count=1, max_missing_hours=0):
    if len(candles) < min_count:
        raise ValueError(f'insufficient historical bars: {len(candles)} < {min_count}')
    missing = 0
    for i, candle in enumerate(candles):
        if not isinstance(candle, Candle):
            raise ValueError('invalid Candle object')
        if i:
            delta = candle.timestamp_ms - candles[i-1].timestamp_ms
            if delta < HOUR_MS or delta % HOUR_MS:
                raise ValueError('duplicate or nonmonotonic hourly bar')
            missing += delta // HOUR_MS - 1
    if missing > max_missing_hours:
        raise ValueError(f'too many missing hourly bars: {missing} > {max_missing_hours}')
    return candles


def fetch_candles(symbol, hours, now_ms=None):
    if symbol not in SYMBOLS:
        raise ValueError('symbol not in public-data allowlist')
    if not isinstance(hours, int) or not 72 <= hours <= 24 * 120:
        raise ValueError('hours outside research limit')
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    cutoff = now_ms // HOUR_MS * HOUR_MS  # newest fully completed hour ends here
    start = cutoff - hours * HOUR_MS
    cursor = start
    results = []
    seen = set()
    while cursor < cutoff:
        size = min(1000, (cutoff - cursor) // HOUR_MS)
        rows = public_get('/api/v3/klines', {'symbol':symbol, 'interval':'1h',
                                            'startTime':cursor, 'endTime':cutoff-1,
                                            'limit':size})
        if not isinstance(rows, list) or not rows:
            raise ValueError('exchange returned empty historical page')
        chunk = [parse_candle(r) for r in rows]
        for bar in chunk:
            if bar.timestamp_ms in seen:
                raise ValueError('duplicate historical bar')
            if not start <= bar.timestamp_ms < cutoff:
                raise ValueError('historical API supplied incomplete/out-of-range bar')
            seen.add(bar.timestamp_ms)
            results.append(bar)
        next_cursor = chunk[-1].timestamp_ms + HOUR_MS
        if next_cursor <= cursor:
            raise ValueError('historical pagination not progressing')
        cursor = next_cursor
        if len(results) > hours:
            raise ValueError('historical page exceeded requested range')
    # Real exchanges sometimes have maintenance/no-trade gaps. NEVER invent
    # missing OHLCV. Reject >0.5% missing hours; simulate no entry near gaps.
    missing_cap = max(1, int(hours * .005))
    validate_candles(results, min_count=hours-missing_cap, max_missing_hours=missing_cap)
    if results[0].timestamp_ms != start or results[-1].timestamp_ms != cutoff - HOUR_MS:
        raise ValueError(f'historical endpoints missing for {symbol}: first={results[0].timestamp_ms}, last={results[-1].timestamp_ms}, expected_start={start}, expected_last={cutoff-HOUR_MS}')
    return results


def fetch_book_ticker(symbol):
    if symbol not in SYMBOLS:
        raise ValueError('symbol not in allowlist')
    data = public_get('/api/v3/ticker/bookTicker', {'symbol':symbol})
    if not isinstance(data, dict) or data.get('symbol') != symbol:
        raise ValueError('invalid bookTicker response')
    bid, ask = number(data.get('bidPrice')), number(data.get('askPrice'))
    bid_qty, ask_qty = number(data.get('bidQty')), number(data.get('askQty'))
    if min(bid, ask) <= 0 or min(bid_qty, ask_qty) < 0 or bid > ask:
        raise ValueError('invalid bid/ask or market size')
    return {'bid':bid, 'ask':ask, 'bid_qty':bid_qty, 'ask_qty':ask_qty,
            'observed_at_utc':datetime.now(timezone.utc).isoformat()}
