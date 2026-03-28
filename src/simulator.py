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
    candle_quality,
    detect_break,
    get_state,
    load_config,
    minor_structure,
    recent_average_range,
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


def run_simulation(limit: int = 800, output_path: str | None = None) -> SimulationResult:
    candles_5m = get_historical_candles('5min', limit)
    open_trades: list[SimTrade] = []
    all_trades: list[SimTrade] = []
    last_setup_key: str | None = None
    current_area: tuple[float, float] | None = None
    active_setup: dict[str, Any] | None = None
    entry_triggered = False
    last_close: float | None = None
    last_bar_close: float | None = None
    stall_count = 0
    setup_count = 0
    blocker_counts: dict[str, int] = {
        'entry_already_used': 0,
        'outside_zone': 0,
        'edge_area': 0,
        'missing_previous_close': 0,
        'insufficient_stall': 0,
        'no_active_setup': 0,
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
                    last_close = None
                    setup_count += 1
                    last_bar_close = candle['close']
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
        low, high = current_area
        mid = (low + high) / 2
        touch_buffer = signal_data.get('touch_buffer', max((high - low) * 0.5, 0.25))
        trigger_low = low - touch_buffer
        trigger_high = high + touch_buffer
        if last_bar_close is not None:
            diff = abs(candle['close'] - last_bar_close)
            stall_count = stall_count + 1 if diff < 0.3 else 0
        blocker_payload = {
            'timestamp': candle['datetime'].isoformat(),
            'signal': signal,
            'price': candle['close'],
            'zone_low': low,
            'zone_high': high,
            'trigger_low': round(trigger_low, 2),
            'trigger_high': round(trigger_high, 2),
            'mid': round(mid, 2),
            'stall_count': stall_count,
        }
        if entry_triggered:
            record_blocker(
                blocker_counts,
                blocker_examples,
                'entry_already_used',
                blocker_payload,
            )
            last_close = candle['close']
            last_bar_close = candle['close']
            continue
        touched_zone = candle['low'] <= trigger_high and candle['high'] >= trigger_low
        effective_price = min(max(candle['close'], trigger_low), trigger_high)
        centered = abs(effective_price - mid) <= (((high - low) * 0.8) + touch_buffer)
        valid_price = last_close is not None
        confirmed = stall_count >= 1
        if not touched_zone:
            record_blocker(blocker_counts, blocker_examples, 'outside_zone', blocker_payload)
        elif not centered:
            record_blocker(blocker_counts, blocker_examples, 'edge_area', blocker_payload)
        elif not valid_price:
            record_blocker(blocker_counts, blocker_examples, 'missing_previous_close', blocker_payload)
        elif not confirmed:
            record_blocker(blocker_counts, blocker_examples, 'insufficient_stall', blocker_payload)
        else:
            entry_triggered = True
            trade = SimTrade(
                opened_at=candle['datetime'].isoformat(),
                signal=signal,
                entry=round(mid, 2),
                entry_low=low,
                entry_high=high,
                sl=signal_data['sl'],
                tp=signal_data['tp'],
                context={
                    'structure': active_setup.get('structure'),
                    'break': active_setup.get('break'),
                    'state': active_setup.get('state'),
                    'impulse': active_setup.get('impulse'),
                    'avg_range': active_setup.get('avg_range'),
                    'simulation_note': 'Entry uses volatility-adaptive zone and touch trigger replay',
                },
            )
            open_trades.append(trade)
            all_trades.append(trade)
        last_close = candle['close']
        last_bar_close = candle['close']

    win_count = sum(1 for trade in all_trades if trade.result == 'win')
    loss_count = sum(1 for trade in all_trades if trade.result == 'loss')
    open_count = sum(1 for trade in all_trades if trade.result == 'open')
    closed_count = win_count + loss_count
    winrate = (win_count / closed_count) * 100 if closed_count else 0.0
    result = SimulationResult(
        symbol=SYMBOL,
        interval='5min->15min replay',
        bars=len(candles_5m),
        fill_model='adaptive_zone_touch_replay',
        warnings=[
            'This is not tick-accurate.',
            'No bid/ask spread, slippage, latency, or partial fills are modeled.',
            'If SL and TP are both touched in the same bar, the simulator assumes SL first.',
            'Setups remain active after the breakout bar so retest bars can be evaluated.',
            'Entry is allowed on touch of a volatility-adaptive trigger band, not only close-inside-zone.',
        ],
        setup_count=setup_count,
        entry_count=len(all_trades),
        win_count=win_count,
        loss_count=loss_count,
        open_count=open_count,
        winrate=round(winrate, 2),
        blocker_counts=blocker_counts,
        blocker_examples=blocker_examples,
        trades=[asdict(trade) for trade in all_trades],
    )
    ensure_data_dir()
    output = Path(output_path) if output_path else DEFAULT_REPORT
    with open(output, 'w', encoding='utf-8') as file:
        json.dump(asdict(result), file, indent=2)
    return result
