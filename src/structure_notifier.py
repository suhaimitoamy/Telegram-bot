from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from src.market_engine import API_KEY, BASE_URL, SYMBOL, load_config, structure


def get_notifier_config() -> dict[str, Any]:
    config = load_config()
    defaults = {
        'bootstrap_bars': 240,
        'max_candles': 400,
        'swing_lookback': 2,
        'retest_tolerance': 0.45,
        'continuation_extension_atr': 1.2,
        'no_retest_bars': 4,
        'active_break_ttl_bars': 12,
        'recovery_gap_seconds': 420,
    }
    notifier = defaults.copy()
    notifier.update(config.get('notifier', {}))
    return notifier


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def fetch_bootstrap_candles(limit: int) -> list[dict[str, Any]]:
    if not API_KEY:
        raise RuntimeError('TWELVE_API_KEY is missing')
    response = requests.get(
        BASE_URL,
        params={
            'symbol': SYMBOL,
            'interval': '5min',
            'outputsize': limit,
            'apikey': API_KEY,
        },
        timeout=20,
    )
    payload = response.json()
    if 'values' not in payload:
        raise RuntimeError(f'Unexpected TwelveData response: {payload}')
    candles = []
    for item in reversed(payload['values']):
        candles.append(
            {
                'datetime': parse_dt(item['datetime']),
                'open': float(item['open']),
                'high': float(item['high']),
                'low': float(item['low']),
                'close': float(item['close']),
            }
        )
    return candles


def aggregate_to_15m(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[datetime, dict[str, Any]] = {}
    order: list[datetime] = []
    for candle in candles:
        dt = candle['datetime']
        bucket = dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)
        if bucket not in buckets:
            buckets[bucket] = {
                'datetime': bucket,
                'open': candle['open'],
                'high': candle['high'],
                'low': candle['low'],
                'close': candle['close'],
            }
            order.append(bucket)
        else:
            target = buckets[bucket]
            target['high'] = max(target['high'], candle['high'])
            target['low'] = min(target['low'], candle['low'])
            target['close'] = candle['close']
    return [buckets[key] for key in order]


def average_range(candles: list[dict[str, Any]], window: int = 10) -> float:
    sample = candles[-window:] if len(candles) >= window else candles
    if not sample:
        return 0.5
    ranges = [max(item['high'] - item['low'], 0.01) for item in sample]
    return sum(ranges) / len(ranges)


def get_bucket_start(dt: datetime) -> datetime:
    return dt.replace(minute=(dt.minute // 5) * 5, second=0, microsecond=0)


def find_latest_confirmed_swings(
    candles: list[dict[str, Any]], lookback: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if len(candles) < (lookback * 2) + 5:
        return None, None

    latest_high = None
    latest_low = None
    start = len(candles) - lookback - 1

    for i in range(start, lookback - 1, -1):
        center = candles[i]
        left = candles[i - lookback:i]
        right = candles[i + 1:i + lookback + 1]
        if latest_high is None and all(center['high'] > item['high'] for item in left + right):
            latest_high = {'price': round(center['high'], 2), 'datetime': center['datetime'].isoformat()}
        if latest_low is None and all(center['low'] < item['low'] for item in left + right):
            latest_low = {'price': round(center['low'], 2), 'datetime': center['datetime'].isoformat()}
        if latest_high and latest_low:
            break
    return latest_high, latest_low


def initialize_runtime_state() -> dict[str, Any]:
    config = get_notifier_config()
    candles = fetch_bootstrap_candles(int(config['bootstrap_bars']))
    return {
        'candles_5m': candles[-int(config['max_candles']):],
        'live_bucket': None,
        'active_break': None,
        'bias': structure(aggregate_to_15m(candles)) if len(candles) >= 60 else 'RANGE',
        'swing_high': None,
        'swing_low': None,
        'last_tick_dt': None,
        'bootstrapped': True,
    }


def refresh_state_from_rest() -> dict[str, Any]:
    return initialize_runtime_state()


def _new_break_event(
    direction: str,
    level: float,
    bias: str,
    closed_candle: dict[str, Any],
    tolerance: float,
) -> dict[str, Any]:
    return {
        'type': 'swing_break',
        'direction': direction,
        'level': round(level, 2),
        'bias': bias,
        'close': round(closed_candle['close'], 2),
        'candle_time': closed_candle['datetime'].isoformat(),
        'retest_low': round(level - tolerance, 2),
        'retest_high': round(level + tolerance, 2),
    }


def process_closed_candle(
    state: dict[str, Any],
    closed_candle: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    candles = state['candles_5m']
    avg_rng = average_range(candles, 10)
    tolerance = max(float(config['retest_tolerance']), round(avg_rng * 0.12, 2))
    bias = structure(aggregate_to_15m(candles)) if len(candles) >= 60 else 'RANGE'
    swing_high, swing_low = find_latest_confirmed_swings(candles, int(config['swing_lookback']))
    state['bias'] = bias
    state['swing_high'] = swing_high
    state['swing_low'] = swing_low

    active = state.get('active_break')
    if active:
        active['bars_since_break'] += 1
        level = float(active['level'])
        direction = active['direction']
        if direction == 'UP':
            touched = closed_candle['low'] <= level + tolerance and closed_candle['high'] >= level - tolerance
            failed = closed_candle['close'] < level - tolerance
            extended = closed_candle['close'] >= active['break_close'] + (avg_rng * float(config['continuation_extension_atr']))
        else:
            touched = closed_candle['high'] >= level - tolerance and closed_candle['low'] <= level + tolerance
            failed = closed_candle['close'] > level + tolerance
            extended = closed_candle['close'] <= active['break_close'] - (avg_rng * float(config['continuation_extension_atr']))

        if failed:
            events.append(
                {
                    'type': 'break_failed',
                    'direction': direction,
                    'level': round(level, 2),
                    'bias': bias,
                    'close': round(closed_candle['close'], 2),
                    'candle_time': closed_candle['datetime'].isoformat(),
                }
            )
            state['active_break'] = None
            active = None
        elif touched and not active.get('retest_alerted'):
            active['retest_alerted'] = True
            active['state'] = 'RETEST_IN_PROGRESS'
            events.append(
                {
                    'type': 'retest_watch',
                    'direction': direction,
                    'level': round(level, 2),
                    'bias': bias,
                    'close': round(closed_candle['close'], 2),
                    'candle_time': closed_candle['datetime'].isoformat(),
                    'retest_low': round(level - tolerance, 2),
                    'retest_high': round(level + tolerance, 2),
                }
            )
        elif (
            not active.get('retest_alerted')
            and not active.get('continuation_alerted')
            and active['bars_since_break'] >= int(config['no_retest_bars'])
            and extended
        ):
            active['continuation_alerted'] = True
            active['state'] = 'CONTINUATION_NO_RETEST'
            events.append(
                {
                    'type': 'continuation_no_retest',
                    'direction': direction,
                    'level': round(level, 2),
                    'bias': bias,
                    'close': round(closed_candle['close'], 2),
                    'extension': round(abs(closed_candle['close'] - level), 2),
                    'candle_time': closed_candle['datetime'].isoformat(),
                }
            )
        elif active['bars_since_break'] > int(config['active_break_ttl_bars']):
            state['active_break'] = None
            active = None

    if swing_high and closed_candle['close'] > swing_high['price'] + (tolerance * 0.1):
        should_replace = (
            state.get('active_break') is None
            or state['active_break']['direction'] != 'UP'
            or swing_high['price'] > state['active_break']['level']
        )
        if should_replace:
            state['active_break'] = {
                'direction': 'UP',
                'level': swing_high['price'],
                'break_close': closed_candle['close'],
                'broken_at': closed_candle['datetime'].isoformat(),
                'bars_since_break': 0,
                'retest_alerted': False,
                'continuation_alerted': False,
                'state': 'WAITING_RETEST',
            }
            events.append(_new_break_event('UP', swing_high['price'], bias, closed_candle, tolerance))

    if swing_low and closed_candle['close'] < swing_low['price'] - (tolerance * 0.1):
        should_replace = (
            state.get('active_break') is None
            or state['active_break']['direction'] != 'DOWN'
            or swing_low['price'] < state['active_break']['level']
        )
        if should_replace:
            state['active_break'] = {
                'direction': 'DOWN',
                'level': swing_low['price'],
                'break_close': closed_candle['close'],
                'broken_at': closed_candle['datetime'].isoformat(),
                'bars_since_break': 0,
                'retest_alerted': False,
                'continuation_alerted': False,
                'state': 'WAITING_RETEST',
            }
            events.append(_new_break_event('DOWN', swing_low['price'], bias, closed_candle, tolerance))

    return events


def update_runtime_with_tick(
    state: dict[str, Any] | None,
    price: float,
    tick_dt: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = get_notifier_config()
    events: list[dict[str, Any]] = []

    if state is None:
        state = initialize_runtime_state()
        events.append({'type': 'status', 'message': 'Bootstrap history loaded. Live notifier is running.'})

    last_tick_dt = state.get('last_tick_dt')
    if last_tick_dt and (tick_dt - last_tick_dt).total_seconds() > int(config['recovery_gap_seconds']):
        state = refresh_state_from_rest()
        events.append({'type': 'status', 'message': 'Gap detected. State refreshed from REST bootstrap.'})

    state['last_tick_dt'] = tick_dt
    bucket_start = get_bucket_start(tick_dt)
    live_bucket = state.get('live_bucket')

    if live_bucket is None:
        state['live_bucket'] = {
            'datetime': bucket_start,
            'open': price,
            'high': price,
            'low': price,
            'close': price,
        }
        return events, state

    if bucket_start == live_bucket['datetime']:
        live_bucket['high'] = max(live_bucket['high'], price)
        live_bucket['low'] = min(live_bucket['low'], price)
        live_bucket['close'] = price
        return events, state

    closed_candle = live_bucket.copy()
    state['candles_5m'].append(closed_candle)
    state['candles_5m'] = state['candles_5m'][-int(config['max_candles']):]
    state['live_bucket'] = {
        'datetime': bucket_start,
        'open': price,
        'high': price,
        'low': price,
        'close': price,
    }
    events.extend(process_closed_candle(state, closed_candle, config))
    return events, state
