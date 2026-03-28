import json
import os
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
    setup = build_setup(price, support, resistance, current_break, state)
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


def run_simulation(limit: int = 800, output_path: str | None = None) -> SimulationResult:
    candles_5m = get_historical_candles('5min', limit)
    open_trades: list[SimTrade] = []
    all_trades: list[SimTrade] = []
    last_setup_key: str | None = None
    current_area: tuple[float, float] | None = None
    entry_triggered = False
    last_close: float | None = None
    last_bar_close: float | None = None
    stall_count = 0
    setup_count = 0

    for index in range(len(candles_5m)):
        window_5m = candles_5m[: index + 1]
        candle = window_5m[-1]
        update_open_trades(open_trades, candle)
        window_15m = aggregate_to_15m(window_5m)
        snapshot = snapshot_from_bars(window_5m, window_15m)
        if not snapshot:
            last_bar_close = candle['close']
            continue
        signal_data = snapshot.get('signal', {})
        signal = signal_data.get('signal')
        if not signal or signal == 'NO TRADE':
            last_bar_close = candle['close']
            continue
        setup_key = (
            f"{snapshot.get('break')}_{signal}_{snapshot.get('support')}_{snapshot.get('resistance')}"
        )
        if setup_key != last_setup_key:
            last_setup_key = setup_key
            entry_triggered = False
            current_area = (signal_data['entry_low'], signal_data['entry_high'])
            stall_count = 0
            last_close = None
            setup_count += 1
            last_bar_close = candle['close']
            continue
        if not current_area or entry_triggered:
            last_bar_close = candle['close']
            continue
        low, high = current_area
        mid = (low + high) / 2
        if last_bar_close is not None:
            diff = abs(candle['close'] - last_bar_close)
            stall_count = stall_count + 1 if diff < 0.3 else 0
        touched_zone = candle['low'] <= high and candle['high'] >= low
        close_inside = low <= candle['close'] <= high
        centered = abs(candle['close'] - mid) <= ((high - low) * 0.6)
        valid_price = last_close is not None
        confirmed = stall_count >= 1
        if touched_zone and close_inside and centered and valid_price and confirmed:
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
                    'structure': snapshot.get('structure'),
                    'break': snapshot.get('break'),
                    'state': snapshot.get('state'),
                    'impulse': snapshot.get('impulse'),
                    'simulation_note': 'Entry uses close-inside-zone with bar replay',
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
        fill_model='conservative_bar_replay',
        warnings=[
            'This is not tick-accurate.',
            'No bid/ask spread, slippage, latency, or partial fills are modeled.',
            'If SL and TP are both touched in the same bar, the simulator assumes SL first.',
            'Entry requires candle close inside the zone, which is intentionally conservative.',
        ],
        setup_count=setup_count,
        entry_count=len(all_trades),
        win_count=win_count,
        loss_count=loss_count,
        open_count=open_count,
        winrate=round(winrate, 2),
        trades=[asdict(trade) for trade in all_trades],
    )
    ensure_data_dir()
    output = Path(output_path) if output_path else DEFAULT_REPORT
    with open(output, 'w', encoding='utf-8') as file:
        json.dump(asdict(result), file, indent=2)
    return result
