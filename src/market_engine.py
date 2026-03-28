import json
import os

import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv('TWELVE_API_KEY')
BASE_URL = 'https://api.twelvedata.com/time_series'
SYMBOL = 'XAU/USD'
DEFAULT_CONFIG = {
    'use_retest': True,
    'use_impulse': False,
    'allow_counter': False,
    'min_rr': 2.0,
}


def load_config():
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return DEFAULT_CONFIG.copy()


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


def get_state(break_type, structure_tf):
    if not break_type:
        return 'NO_SETUP'
    if structure_tf == 'UPTREND' and break_type == 'BREAK_DOWN':
        return 'COUNTER'
    if structure_tf == 'DOWNTREND' and break_type == 'BREAK_UP':
        return 'COUNTER'
    return 'VALID'


def build_setup(price, support, resistance, break_type, state):
    config = load_config()
    if not config.get('allow_counter', False) and state == 'COUNTER':
        return {'signal': 'NO TRADE'}
    rr = config.get('min_rr', 2.0)
    if break_type == 'BREAK_UP':
        entry_low = price - 1.0
        entry_high = price + 0.5
        sl = support - 1.0
        risk = entry_high - sl
        tp = entry_high + (risk * rr)
        return {
            'signal': 'BUY',
            'entry_low': round(entry_low, 2),
            'entry_high': round(entry_high, 2),
            'sl': round(sl, 2),
            'tp': round(tp, 2),
        }
    if break_type == 'BREAK_DOWN':
        entry_low = price - 0.5
        entry_high = price + 1.0
        sl = resistance + 1.0
        risk = sl - entry_low
        tp = entry_low - (risk * rr)
        return {
            'signal': 'SELL',
            'entry_low': round(entry_low, 2),
            'entry_high': round(entry_high, 2),
            'sl': round(sl, 2),
            'tp': round(tp, 2),
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
    setup = build_setup(price, support, resistance, current_break, state)
    return {
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
