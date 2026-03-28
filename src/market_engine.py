import copy
import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv('TWELVE_API_KEY')
BASE_URL = 'https://api.twelvedata.com/time_series'
SYMBOL = 'XAU/USD'
DEFAULT_PROFILE_FILTERS = {
    'BUY_UPTREND': {
        'enabled': False,
        'min_setup_quality': 6,
        'min_confirmation_score': 4,
        'max_setup_age_bars': 8,
        'depth_min': 0.18,
        'depth_max': 0.85,
        'required_stall': 1,
        'require_reclaim': True,
    },
    'SELL_DOWNTREND': {
        'enabled': True,
        'min_setup_quality': 5,
        'min_confirmation_score': 3,
        'max_setup_age_bars': 10,
        'depth_min': 0.18,
        'depth_max': 0.90,
        'required_stall': 0,
        'require_reclaim': True,
    },
    'BUY_RANGE': {
        'enabled': False,
        'min_setup_quality': 6,
        'min_confirmation_score': 4,
        'max_setup_age_bars': 6,
        'depth_min': 0.20,
        'depth_max': 0.80,
        'required_stall': 1,
        'require_reclaim': True,
    },
    'SELL_RANGE': {
        'enabled': True,
        'min_setup_quality': 5,
        'min_confirmation_score': 4,
        'max_setup_age_bars': 6,
        'depth_min': 0.20,
        'depth_max': 0.85,
        'required_stall': 1,
        'require_reclaim': True,
    },
}
DEFAULT_CONFIG = {
    'use_retest': True,
    'use_impulse': False,
    'allow_counter': False,
    'min_rr': 2.0,
    'profile_filters': DEFAULT_PROFILE_FILTERS,
}


def load_config():
    merged = copy.deepcopy(DEFAULT_CONFIG)
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception:
        return merged

    for key, value in raw.items():
        if key == 'profile_filters' and isinstance(value, dict):
            continue
        merged[key] = value

    user_profiles = raw.get('profile_filters', {}) if isinstance(raw, dict) else {}
    for profile_key, overrides in user_profiles.items():
        base = merged['profile_filters'].get(profile_key, {}).copy()
        if isinstance(overrides, dict):
            base.update(overrides)
        merged['profile_filters'][profile_key] = base
    return merged


def get_profile_key(signal, structure_tf):
    return f'{signal}_{structure_tf}'


def get_profile_rules(config, profile_key):
    return copy.deepcopy(config.get('profile_filters', {}).get(profile_key, {}))


def get_candles(tf='5min', limit=200):
    try:
        response = requests.get(
            BASE_URL,
            params={
                'symbol': SYMBOL,
                'interval': tf,
                'outputsize': limit,
                'apikey': API_KEY,
            },
            timeout=10,
        )
        js = response.json()
        if 'values' not in js:
            return []
        return [
            {
                'open': float(v['open']),
                'high': float(v['high']),
                'low': float(v['low']),
                'close': float(v['close']),
            }
            for v in reversed(js['values'])
        ]
    except Exception:
        return []


def structure(data):
    if len(data) < 20:
        return 'RANGE'
    h1, h2 = data[-1]['high'], data[-5]['high']
    l1, l2 = data[-1]['low'], data[-5]['low']
    if h1 > h2 and l1 > l2:
        return 'UPTREND'
    if h1 < h2 and l1 < l2:
        return 'DOWNTREND'
    return 'RANGE'


def minor_structure(data):
    last_high = None
    last_low = None
    for i in range(len(data) - 2, 1, -1):
        c = data[i]
        if c['high'] > data[i - 1]['high'] and c['high'] > data[i - 2]['high']:
            last_high = c['high']
            break
    for i in range(len(data) - 2, 1, -1):
        c = data[i]
        if c['low'] < data[i - 1]['low'] and c['low'] < data[i - 2]['low']:
            last_low = c['low']
            break
    if last_low is None or last_high is None:
        return None, None
    return round(last_low, 2), round(last_high, 2)


def detect_break(data, support, resistance):
    last = data[-1]
    if last['close'] > resistance:
        return 'BREAK_UP'
    if last['close'] < support:
        return 'BREAK_DOWN'
    return None


def validate_break(data, break_type):
    last = data[-1]
    prev = data[-2]
    body = abs(last['close'] - last['open'])
    prev_body = abs(prev['close'] - prev['open'])
    upper_wick = last['high'] - max(last['open'], last['close'])
    lower_wick = min(last['open'], last['close']) - last['low']
    if body < (upper_wick + lower_wick):
        return False
    if body < prev_body:
        return False
    if break_type == 'BREAK_UP' and upper_wick > body:
        return False
    if break_type == 'BREAK_DOWN' and lower_wick > body:
        return False
    return True


def candle_quality(candle, prev, data):
    body = abs(candle['close'] - candle['open'])
    upper_wick = candle['high'] - max(candle['open'], candle['close'])
    lower_wick = min(candle['open'], candle['close']) - candle['low']
    clean = body > (upper_wick + lower_wick)
    momentum = body > abs(prev['close'] - prev['open'])
    ranges = [(x['high'] - x['low']) for x in data[-5:]]
    avg_range = sum(ranges) / len(ranges)
    volatility = avg_range > 1.0
    return {
        'clean': clean,
        'momentum': momentum,
        'volatility': volatility,
    }


def candle_metrics(candle):
    body = abs(candle['close'] - candle['open'])
    upper_wick = candle['high'] - max(candle['open'], candle['close'])
    lower_wick = min(candle['open'], candle['close']) - candle['low']
    total_range = max(candle['high'] - candle['low'], 0.01)
    body_ratio = body / total_range
    return {
        'body': body,
        'upper_wick': upper_wick,
        'lower_wick': lower_wick,
        'range': total_range,
        'body_ratio': body_ratio,
        'bullish': candle['close'] > candle['open'],
        'bearish': candle['close'] < candle['open'],
    }


def recent_average_range(data, window=10):
    sample = data[-window:] if len(data) >= window else data
    if not sample:
        return 0.5
    ranges = [max(item['high'] - item['low'], 0.01) for item in sample]
    return sum(ranges) / len(ranges)


def get_state(break_type, structure_tf):
    if not break_type:
        return 'NO_SETUP'
    if structure_tf == 'UPTREND' and break_type == 'BREAK_DOWN':
        return 'COUNTER'
    if structure_tf == 'DOWNTREND' and break_type == 'BREAK_UP':
        return 'COUNTER'
    return 'VALID'


def is_trend_aligned(signal, structure_tf):
    return (
        (signal == 'BUY' and structure_tf == 'UPTREND')
        or (signal == 'SELL' and structure_tf == 'DOWNTREND')
    )


def setup_quality_score(break_type, structure_tf, candle, prev, data):
    signal = 'BUY' if break_type == 'BREAK_UP' else 'SELL'
    quality = candle_quality(candle, prev, data)
    metrics = candle_metrics(candle)
    prev_metrics = candle_metrics(prev)
    avg_range = recent_average_range(data, 10)

    score = 0
    tags = []

    if quality['clean']:
        score += 1
        tags.append('clean_break')
    if quality['momentum']:
        score += 1
        tags.append('momentum_break')
    if metrics['body_ratio'] >= 0.55:
        score += 1
        tags.append('body_dominant')
    if metrics['body'] >= max(prev_metrics['body'] * 1.1, 0.25):
        score += 1
        tags.append('body_expansion')
    if metrics['range'] >= max(avg_range * 0.9, 0.5):
        score += 1
        tags.append('range_expansion')
    if is_trend_aligned(signal, structure_tf):
        score += 1
        tags.append('trend_aligned')

    return score, tags


def build_setup(price, support, resistance, break_type, state, zone_half_width, sl_buffer):
    config = load_config()
    if not config.get('allow_counter', False) and state == 'COUNTER':
        return {'signal': 'NO TRADE'}
    rr = config.get('min_rr', 2.0)
    touch_buffer = max(zone_half_width * 0.5, 0.25)
    if break_type == 'BREAK_UP':
        entry_low = resistance - zone_half_width
        entry_high = resistance + zone_half_width
        sl = support - sl_buffer
        entry = (entry_low + entry_high) / 2
        risk = max(entry - sl, 0.1)
        tp = entry + (risk * rr)
        return {
            'signal': 'BUY',
            'entry_low': round(entry_low, 2),
            'entry_high': round(entry_high, 2),
            'sl': round(sl, 2),
            'tp': round(tp, 2),
            'touch_buffer': round(touch_buffer, 2),
            'zone_half_width': round(zone_half_width, 2),
        }
    if break_type == 'BREAK_DOWN':
        entry_low = support - zone_half_width
        entry_high = support + zone_half_width
        sl = resistance + sl_buffer
        entry = (entry_low + entry_high) / 2
        risk = max(sl - entry, 0.1)
        tp = entry - (risk * rr)
        return {
            'signal': 'SELL',
            'entry_low': round(entry_low, 2),
            'entry_high': round(entry_high, 2),
            'sl': round(sl, 2),
            'tp': round(tp, 2),
            'touch_buffer': round(touch_buffer, 2),
            'zone_half_width': round(zone_half_width, 2),
        }
    return {'signal': 'NO TRADE'}


def snapshot(external_price=None):
    config = load_config()
    m15 = get_candles('15min')
    m5 = get_candles('5min')
    if not m15 or not m5:
        return None
    if external_price is not None:
        m5[-1]['close'] = external_price
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
        'profile_rules': get_profile_rules(config, get_profile_key(setup.get('signal'), structure_tf)) if setup.get('signal') else {},
        'signal': setup,
    }
