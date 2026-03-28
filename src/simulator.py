import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from src.market_engine import (
    API_KEY,
    BASE_URL,
    SYMBOL,
    build_setup,
    candle_metrics,
    candle_quality,
    detect_break,
    get_state,
    is_trend_aligned,
    load_config,
    minor_structure,
    recent_average_range,
    setup_quality_score,
    structure,
    validate_break,
)

load_dotenv()
DATA_DIR = Path('data')
DEFAULT_REPORT = DATA_DIR / 'simulation_report.json'


@dataclass
class SimTrade:
    opened_at: str
    signal: str
    entry: float
    entry_low: float
    entry_high: float
    sl: float
    tp: float
    context: dict[str, Any]
    result: str = 'open'
    closed_at: str | None = None
    exit_price: float | None = None
    exit_reason: str | None = None


@dataclass
class SimulationResult:
    symbol: str
    interval: str
    bars: int
    fill_model: str
    warnings: list[str]
    setup_count: int
    entry_count: int
    win_count: int
    loss_count: int
    open_count: int
    winrate: float
    blocker_counts: dict[str, int]
    blocker_examples: dict[str, list[dict[str, Any]]]
    profile_stats: dict[str, Any]
    trades: list[dict[str, Any]]


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_historical_candles(tf: str = '5min', limit: int = 800) -> list[dict[str, Any]]:
    if not API_KEY:
        raise RuntimeError('TWELVE_API_KEY is missing')
    response = requests.get(
        BASE_URL,
        params={
            'symbol': SYMBOL,
            'interval': tf,
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


def snapshot_from_bars(m5: list[dict[str, Any]], m15: list[dict[str, Any]]) -> dict[str, Any] | None:
    config = load_config()
    if len(m5) < 20 or len(m15) < 20:
        return None
    price = round(m5[-1]['close'], 2)
    structure_tf = structure(m15)
    support, resistance = minor_structure(m5)
    if support is None or resistance is None:
        return None
    current_break = detect_break(m5, support, resistance)
    if not current_break:
        return None
    if not validate_break(m5, current_break):
        return None
    state = get_state(current_break, structure_tf)
    last = m5[-1]
    prev = m5[-2]
    quality = candle_quality(last, prev, m5)
    impulse = quality['momentum'] and quality['clean']
    if config.get('use_impulse', False) and not impulse:
        return None
    avg_range = recent_average_range(m5, 10)
    break_span = max(abs(resistance - support), avg_range)
    zone_half_width = min(max(avg_range * 0.35, 0.6), max(1.8, break_span * 0.6))
    sl_buffer = max(zone_half_width * 1.25, 1.0)
    quality_score, quality_tags = setup_quality_score(current_break, structure_tf, last, prev, m5)
    setup = build_setup(
        price,
        support,
        resistance,
        current_break,
        state,
        zone_half_width=zone_half_width,
        sl_buffer=sl_buffer,
    )
    return {
        'timestamp': m5[-1]['datetime'].isoformat(),
        'price': price,
        'support': support,
        'resistance': resistance,
        'structure': structure_tf,
        'break': current_break,
        'state': state,
        'quality': quality,
        'impulse': impulse,
        'avg_range': round(avg_range, 2),
        'setup_quality_score': quality_score,
        'setup_quality_tags': quality_tags,
        'signal': setup,
    }


def update_open_trades(open_trades: list[SimTrade], candle: dict[str, Any]) -> None:
    for trade in open_trades:
        if trade.result != 'open':
            continue
        closed_at = candle['datetime'].isoformat()
        if trade.signal == 'BUY':
            hit_sl = candle['low'] <= trade.sl
            hit_tp = candle['high'] >= trade.tp
            if hit_sl:
                trade.result = 'loss'
                trade.closed_at = closed_at
                trade.exit_price = trade.sl
                trade.exit_reason = 'sl'
            elif hit_tp:
                trade.result = 'win'
                trade.closed_at = closed_at
                trade.exit_price = trade.tp
                trade.exit_reason = 'tp'
        elif trade.signal == 'SELL':
            hit_sl = candle['high'] >= trade.sl
            hit_tp = candle['low'] <= trade.tp
            if hit_sl:
                trade.result = 'loss'
                trade.closed_at = closed_at
                trade.exit_price = trade.sl
                trade.exit_reason = 'sl'
            elif hit_tp:
                trade.result = 'win'
                trade.closed_at = closed_at
                trade.exit_price = trade.tp
                trade.exit_reason = 'tp'


def record_blocker(
    blocker_counts: dict[str, int],
    blocker_examples: dict[str, list[dict[str, Any]]],
    name: str,
    payload: dict[str, Any],
) -> None:
    blocker_counts[name] = blocker_counts.get(name, 0) + 1
    blocker_examples.setdefault(name, [])
    if len(blocker_examples[name]) < 5:
        blocker_examples[name].append(payload)


def get_profile_key(signal: str, structure_tf: str) -> str:
    return f'{signal}_{structure_tf}'


def ensure_profile_bucket(profile_stats: dict[str, Any], profile_key: str) -> dict[str, Any]:
    if profile_key not in profile_stats:
        profile_stats[profile_key] = {
            'setups': 0,
            'entries': 0,
            'wins': 0,
            'losses': 0,
            'open': 0,
            'blockers': {},
        }
    return profile_stats[profile_key]


def increment_profile_metric(profile_stats: dict[str, Any], profile_key: str, metric: str) -> None:
    bucket = ensure_profile_bucket(profile_stats, profile_key)
    bucket[metric] = bucket.get(metric, 0) + 1


def record_profile_blocker(profile_stats: dict[str, Any], profile_key: str, blocker_name: str) -> None:
    bucket = ensure_profile_bucket(profile_stats, profile_key)
    bucket['blockers'][blocker_name] = bucket['blockers'].get(blocker_name, 0) + 1


def is_pin_bar(candle: dict[str, Any], signal: str) -> bool:
    metrics = candle_metrics(candle)
    if signal == 'BUY':
        return (
            metrics['lower_wick'] >= max(metrics['body'] * 1.5, metrics['range'] * 0.35)
            and candle['close'] >= (candle['low'] + (metrics['range'] * 0.55))
        )
    return (
        metrics['upper_wick'] >= max(metrics['body'] * 1.5, metrics['range'] * 0.35)
        and candle['close'] <= (candle['high'] - (metrics['range'] * 0.55))
    )


def is_engulfing(prev: dict[str, Any], candle: dict[str, Any], signal: str) -> bool:
    prev_high_body = max(prev['open'], prev['close'])
    prev_low_body = min(prev['open'], prev['close'])
    curr_high_body = max(candle['open'], candle['close'])
    curr_low_body = min(candle['open'], candle['close'])

    if signal == 'BUY':
        return (
            prev['close'] < prev['open']
            and candle['close'] > candle['open']
            and curr_low_body <= prev_low_body
            and curr_high_body >= prev_high_body
        )
    return (
        prev['close'] > prev['open']
        and candle['close'] < candle['open']
        and curr_high_body >= prev_high_body
        and curr_low_body <= prev_low_body
    )


def is_reclaim_confirmation(candle: dict[str, Any], signal: str, zone_low: float, zone_high: float) -> bool:
    mid = (zone_low + zone_high) / 2
    if signal == 'BUY':
        return candle['close'] >= mid and candle['close'] > candle['open']
    return candle['close'] <= mid and candle['close'] < candle['open']


def is_momentum_followthrough(candle: dict[str, Any], signal: str, avg_range: float) -> bool:
    metrics = candle_metrics(candle)
    min_body = max(avg_range * 0.3, 0.25)
    if signal == 'BUY':
        return metrics['bullish'] and metrics['body'] >= min_body and metrics['body_ratio'] >= 0.45
    return metrics['bearish'] and metrics['body'] >= min_body and metrics['body_ratio'] >= 0.45


def get_stall_rules(active_setup: dict[str, Any], signal: str) -> dict[str, Any]:
    avg_range = max(float(active_setup.get('avg_range') or 0.5), 0.5)
    structure_tf = active_setup.get('structure') or 'RANGE'
    setup_quality = int(active_setup.get('setup_quality_score') or 0)
    impulse = bool(active_setup.get('impulse'))

    quiet_close_threshold = max(round(avg_range * 0.18, 2), 0.2)
    quiet_body_threshold = max(round(avg_range * 0.25, 2), 0.25)
    quiet_range_threshold = max(round(avg_range * 0.9, 2), 0.6)

    required_stall = 0 if is_trend_aligned(signal, structure_tf) and impulse and setup_quality >= 4 else 1
    if structure_tf == 'RANGE':
        required_stall = max(required_stall, 1)

    return {
        'quiet_close_threshold': quiet_close_threshold,
        'quiet_body_threshold': quiet_body_threshold,
        'quiet_range_threshold': quiet_range_threshold,
        'required_stall': required_stall,
    }


def get_confirmation_threshold(active_setup: dict[str, Any], signal: str) -> int:
    structure_tf = active_setup.get('structure') or 'RANGE'
    return 2 if is_trend_aligned(signal, structure_tf) else 3


def get_confirmation_score(
    prev_candle: dict[str, Any],
    candle: dict[str, Any],
    active_setup: dict[str, Any],
    zone_low: float,
    zone_high: float,
) -> tuple[int, list[str]]:
    signal = active_setup['signal']['signal']
    avg_range = max(float(active_setup.get('avg_range') or 0.5), 0.5)

    score = 0
    tags: list[str] = []

    if is_reclaim_confirmation(candle, signal, zone_low, zone_high):
        score += 2
        tags.append('reclaim_close')
    if is_pin_bar(candle, signal):
        score += 2
        tags.append('pin_bar')
    if is_engulfing(prev_candle, candle, signal):
        score += 2
        tags.append('engulfing')
    if is_momentum_followthrough(candle, signal, avg_range):
        score += 1
        tags.append('momentum_followthrough')
    if bool(active_setup.get('impulse')):
        score += 1
        tags.append('impulse_breakout')
    if int(active_setup.get('setup_quality_score') or 0) >= 4:
        score += 1
        tags.append('high_quality_setup')

    return score, tags


def run_simulation(limit: int = 800, output_path: str | None = None) -> SimulationResult:
    candles_5m = get_historical_candles('5min', limit)
    open_trades: list[SimTrade] = []
    all_trades: list[SimTrade] = []
    last_setup_key: str | None = None
    current_area: tuple[float, float] | None = None
    active_setup: dict[str, Any] | None = None
    entry_triggered = False
    last_bar_close: float | None = None
    stall_count = 0
    setup_count = 0
    active_setup_age = 0
    profile_stats: dict[str, Any] = {}
    blocker_counts: dict[str, int] = {
        'entry_already_used': 0,
        'outside_zone': 0,
        'edge_area': 0,
        'insufficient_stall': 0,
        'no_active_setup': 0,
        'setup_expired': 0,
        'bad_retest_depth': 0,
        'weak_confirmation': 0,
    }
    blocker_examples: dict[str, list[dict[str, Any]]] = {}

    for index in range(len(candles_5m)):
        window_5m = candles_5m[: index + 1]
        candle = window_5m[-1]
        update_open_trades(open_trades, candle)
        window_15m = aggregate_to_15m(window_5m)
        snapshot = snapshot_from_bars(window_5m, window_15m)

        if snapshot:
            signal_data = snapshot.get('signal', {})
            signal = signal_data.get('signal')
            break_type = snapshot.get('break')
            if signal and signal != 'NO TRADE' and break_type:
                setup_key = (
                    f"{snapshot.get('break')}_{signal}_{snapshot.get('support')}_{snapshot.get('resistance')}"
                )
                if setup_key != last_setup_key:
                    last_setup_key = setup_key
                    entry_triggered = False
                    current_area = (signal_data['entry_low'], signal_data['entry_high'])
                    active_setup = snapshot
                    stall_count = 0
                    setup_count += 1
                    active_setup_age = 0
                    last_bar_close = candle['close']
                    profile_key = get_profile_key(signal, snapshot.get('structure'))
                    increment_profile_metric(profile_stats, profile_key, 'setups')
                    continue

        if not current_area or not active_setup:
            record_blocker(
                blocker_counts,
                blocker_examples,
                'no_active_setup',
                {
                    'timestamp': candle['datetime'].isoformat(),
                    'price': candle['close'],
                },
            )
            last_bar_close = candle['close']
            continue

        signal_data = active_setup.get('signal', {})
        signal = signal_data.get('signal')
        if not signal or signal == 'NO TRADE':
            last_bar_close = candle['close']
            continue

        structure_tf = active_setup.get('structure') or 'RANGE'
        profile_key = get_profile_key(signal, structure_tf)
        active_setup_age += 1
        max_setup_age_bars = 8 if structure_tf == 'RANGE' else 10

        low, high = current_area
        mid = (low + high) / 2
        touch_buffer = signal_data.get('touch_buffer', max((high - low) * 0.5, 0.25))
        trigger_low = low - touch_buffer
        trigger_high = high + touch_buffer
        band_width = max(trigger_high - trigger_low, 0.01)

        close_move = abs(candle['close'] - last_bar_close) if last_bar_close is not None else None
        body = abs(candle['close'] - candle['open'])
        bar_range = candle['high'] - candle['low']
        touched_zone = candle['low'] <= trigger_high and candle['high'] >= trigger_low

        if signal == 'BUY':
            depth = (trigger_high - candle['low']) / band_width
        else:
            depth = (candle['high'] - trigger_low) / band_width
        depth = round(depth, 2)
        depth_ok = 0.12 <= depth <= 1.05

        rules = get_stall_rules(active_setup, signal)
        quiet_bar = (
            close_move is not None
            and close_move <= rules['quiet_close_threshold']
            and body <= rules['quiet_body_threshold']
            and bar_range <= rules['quiet_range_threshold']
        )

        if touched_zone and quiet_bar:
            stall_count += 1
        elif not touched_zone:
            stall_count = 0

        prev_candle = window_5m[-2] if len(window_5m) >= 2 else candle
        confirmation_score, confirmation_tags = get_confirmation_score(prev_candle, candle, active_setup, low, high)
        confirmation_needed = get_confirmation_threshold(active_setup, signal)
        confirmation_ok = confirmation_score >= confirmation_needed
        stall_ok = stall_count >= rules['required_stall']
        effective_price = min(max(candle['close'], trigger_low), trigger_high)
        centered = abs(effective_price - mid) <= (((high - low) * 0.8) + touch_buffer)

        blocker_payload = {
            'timestamp': candle['datetime'].isoformat(),
            'signal': signal,
            'structure': structure_tf,
            'price': candle['close'],
            'zone_low': low,
            'zone_high': high,
            'trigger_low': round(trigger_low, 2),
            'trigger_high': round(trigger_high, 2),
            'mid': round(mid, 2),
            'stall_count': stall_count,
            'required_stall': rules['required_stall'],
            'setup_age_bars': active_setup_age,
            'max_setup_age_bars': max_setup_age_bars,
            'retest_depth': depth,
            'confirmation_score': confirmation_score,
            'confirmation_needed': confirmation_needed,
            'confirmation_tags': confirmation_tags,
            'setup_quality_score': active_setup.get('setup_quality_score'),
            'setup_quality_tags': active_setup.get('setup_quality_tags'),
        }

        if not entry_triggered and active_setup_age > max_setup_age_bars:
            record_blocker(blocker_counts, blocker_examples, 'setup_expired', blocker_payload)
            record_profile_blocker(profile_stats, profile_key, 'setup_expired')
            current_area = None
            active_setup = None
            stall_count = 0
            active_setup_age = 0
            last_bar_close = candle['close']
            continue

        if entry_triggered:
            record_blocker(
                blocker_counts,
                blocker_examples,
                'entry_already_used',
                blocker_payload,
            )
            record_profile_blocker(profile_stats, profile_key, 'entry_already_used')
            last_bar_close = candle['close']
            continue

        if not touched_zone:
            record_blocker(blocker_counts, blocker_examples, 'outside_zone', blocker_payload)
            record_profile_blocker(profile_stats, profile_key, 'outside_zone')
        elif not depth_ok:
            record_blocker(blocker_counts, blocker_examples, 'bad_retest_depth', blocker_payload)
            record_profile_blocker(profile_stats, profile_key, 'bad_retest_depth')
        elif not centered:
            record_blocker(blocker_counts, blocker_examples, 'edge_area', blocker_payload)
            record_profile_blocker(profile_stats, profile_key, 'edge_area')
        elif not confirmation_ok:
            record_blocker(blocker_counts, blocker_examples, 'weak_confirmation', blocker_payload)
            record_profile_blocker(profile_stats, profile_key, 'weak_confirmation')
        elif not stall_ok:
            record_blocker(blocker_counts, blocker_examples, 'insufficient_stall', blocker_payload)
            record_profile_blocker(profile_stats, profile_key, 'insufficient_stall')
        else:
            entry_triggered = True
            entry_price = round(effective_price, 2)
            trade = SimTrade(
                opened_at=candle['datetime'].isoformat(),
                signal=signal,
                entry=entry_price,
                entry_low=low,
                entry_high=high,
                sl=signal_data['sl'],
                tp=signal_data['tp'],
                context={
                    'structure': structure_tf,
                    'break': active_setup.get('break'),
                    'state': active_setup.get('state'),
                    'impulse': active_setup.get('impulse'),
                    'avg_range': active_setup.get('avg_range'),
                    'setup_quality_score': active_setup.get('setup_quality_score'),
                    'setup_quality_tags': active_setup.get('setup_quality_tags'),
                    'confirmation_score': confirmation_score,
                    'confirmation_tags': confirmation_tags,
                    'profile_key': profile_key,
                    'setup_age_bars': active_setup_age,
                    'retest_depth': depth,
                    'stall_count': stall_count,
                    'simulation_note': 'Entry uses setup TTL, retest-depth filter, confirmation scoring, and adaptive stall.',
                },
            )
            open_trades.append(trade)
            all_trades.append(trade)
            increment_profile_metric(profile_stats, profile_key, 'entries')

        last_bar_close = candle['close']

    for trade in all_trades:
        profile_key = trade.context.get('profile_key')
        if not profile_key:
            continue
        if trade.result == 'win':
            increment_profile_metric(profile_stats, profile_key, 'wins')
        elif trade.result == 'loss':
            increment_profile_metric(profile_stats, profile_key, 'losses')
        else:
            increment_profile_metric(profile_stats, profile_key, 'open')

    win_count = sum(1 for trade in all_trades if trade.result == 'win')
    loss_count = sum(1 for trade in all_trades if trade.result == 'loss')
    open_count = sum(1 for trade in all_trades if trade.result == 'open')
    closed_count = win_count + loss_count
    winrate = (win_count / closed_count) * 100 if closed_count else 0.0
    result = SimulationResult(
        symbol=SYMBOL,
        interval='5min->15min replay',
        bars=len(candles_5m),
        fill_model='adaptive_confirmation_touch_replay',
        warnings=[
            'This is not tick-accurate.',
            'No bid/ask spread, slippage, latency, or partial fills are modeled.',
            'If SL and TP are both touched in the same bar, the simulator assumes SL first.',
            'Setups remain active after the breakout bar so retest bars can be evaluated.',
            'Setups expire if the retest takes too long.',
            'Entry requires acceptable retest depth, confirmation score, and adaptive stall when needed.',
        ],
        setup_count=setup_count,
        entry_count=len(all_trades),
        win_count=win_count,
        loss_count=loss_count,
        open_count=open_count,
        winrate=round(winrate, 2),
        blocker_counts=blocker_counts,
        blocker_examples=blocker_examples,
        profile_stats=profile_stats,
        trades=[asdict(trade) for trade in all_trades],
    )
    ensure_data_dir()
    output = Path(output_path) if output_path else DEFAULT_REPORT
    with open(output, 'w', encoding='utf-8') as file:
        json.dump(asdict(result), file, indent=2)
    return result
