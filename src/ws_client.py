import json
import os
import time

import websocket
from dotenv import load_dotenv

from src.market_engine import is_trend_aligned, snapshot
from src.telegram_bot import send_entry, send_setup
from src.trade_memory import log_trade
from src.tracker import update_results

load_dotenv()
API_KEY = os.getenv('TWELVE_API_KEY')

last_price = None
last_setup_key = None
entry_triggered = False
current_area = None
active_setup = None
running = True
last_tick_price = None
stall_count = 0
setup_started_at = None


def get_stall_rules(active_setup, signal):
    avg_range = max(float(active_setup.get('avg_range') or 0.5), 0.5)
    structure_tf = active_setup.get('structure') or 'RANGE'
    setup_quality = int(active_setup.get('setup_quality_score') or 0)
    impulse = bool(active_setup.get('impulse'))

    quiet_move_threshold = max(round(avg_range * 0.12, 2), 0.15)
    required_stall = 0 if is_trend_aligned(signal, structure_tf) and impulse and setup_quality >= 4 else 1
    if structure_tf == 'RANGE':
        required_stall = max(required_stall, 1)

    return {
        'quiet_move_threshold': quiet_move_threshold,
        'required_stall': required_stall,
    }


def confirmation_threshold(active_setup, signal):
    structure_tf = active_setup.get('structure') or 'RANGE'
    return 1 if is_trend_aligned(signal, structure_tf) else 2


def price_confirmation_score(signal, price, zone_low, zone_high, active_setup):
    mid = (zone_low + zone_high) / 2
    score = 0
    tags = []

    if signal == 'BUY' and price >= mid:
        score += 1
        tags.append('reclaim_mid')
    if signal == 'SELL' and price <= mid:
        score += 1
        tags.append('reclaim_mid')

    if bool(active_setup.get('impulse')):
        score += 1
        tags.append('impulse_breakout')

    if int(active_setup.get('setup_quality_score') or 0) >= 4:
        score += 1
        tags.append('high_quality_setup')

    return score, tags


def process(price):
    global last_setup_key, entry_triggered, current_area, active_setup
    global last_tick_price, stall_count, setup_started_at

    data = snapshot(external_price=price)
    if data:
        signal_data = data.get('signal', {})
        signal = signal_data.get('signal')
        break_type = data.get('break')
        if signal and signal != 'NO TRADE' and break_type:
            entry_low = signal_data.get('entry_low')
            entry_high = signal_data.get('entry_high')
            setup_key = f"{break_type}_{signal}_{data.get('support')}_{data.get('resistance')}"
            if setup_key != last_setup_key:
                last_setup_key = setup_key
                entry_triggered = False
                current_area = (entry_low, entry_high)
                active_setup = data
                stall_count = 0
                last_tick_price = None
                setup_started_at = time.time()
                print(
                    f"📡 SETUP {signal} | Area {entry_low}-{entry_high} "
                    f"| quality={data.get('setup_quality_score')} tags={data.get('setup_quality_tags')}"
                )
                send_setup(data)
                return

    if not current_area or not active_setup:
        return

    signal_data = active_setup.get('signal', {})
    signal = signal_data.get('signal')
    if not signal or signal == 'NO TRADE':
        return

    max_setup_age_seconds = 40 * 60
    if not entry_triggered and setup_started_at and (time.time() - setup_started_at) > max_setup_age_seconds:
        print(f'[SETUP EXPIRED] signal={signal} age_seconds={round(time.time() - setup_started_at, 2)}')
        current_area = None
        active_setup = None
        stall_count = 0
        last_tick_price = None
        setup_started_at = None
        return

    low, high = current_area
    mid = (low + high) / 2
    touch_buffer = signal_data.get('touch_buffer', max((high - low) * 0.5, 0.25))
    trigger_low = low - touch_buffer
    trigger_high = high + touch_buffer
    band_width = max(trigger_high - trigger_low, 0.01)

    rules = get_stall_rules(active_setup, signal)
    if last_tick_price is not None:
        diff = abs(price - last_tick_price)
        stall_count = stall_count + 1 if diff <= rules['quiet_move_threshold'] else 0
    last_tick_price = price

    if not entry_triggered and trigger_low <= price <= trigger_high:
        if signal == 'BUY':
            depth = (trigger_high - price) / band_width
        else:
            depth = (price - trigger_low) / band_width
        if not (0.12 <= depth <= 1.05):
            print(f'[ENTRY BLOCKED] bad depth | signal={signal} price={price} depth={round(depth, 2)}')
            return

        effective_band = ((high - low) * 0.8) + touch_buffer
        if abs(price - mid) > effective_band:
            print(
                f'[ENTRY BLOCKED] edge area | price={price} mid={mid} '
                f'trigger_low={trigger_low} trigger_high={trigger_high}'
            )
            return

        score, tags = price_confirmation_score(signal, price, low, high, active_setup)
        needed_score = confirmation_threshold(active_setup, signal)
        if score < needed_score:
            print(
                f'[ENTRY BLOCKED] weak confirmation | signal={signal} price={price} '
                f'score={score} needed={needed_score} tags={tags}'
            )
            return

        if stall_count < rules['required_stall']:
            print(
                f'[ENTRY BLOCKED] confirmation failed | signal={signal} price={price} '
                f'stall={stall_count} required={rules["required_stall"]}'
            )
            return

        entry_triggered = True
        print(f'🚀 ENTRY TRIGGERED {signal} @ {price}')
        send_entry(active_setup)
        entry = round(price, 2)
        log_trade({
            'signal': signal,
            'entry': entry,
            'entry_low': low,
            'entry_high': high,
            'sl': signal_data.get('sl'),
            'tp': signal_data.get('tp'),
            'context': {
                'structure': active_setup.get('structure'),
                'break': active_setup.get('break'),
                'state': active_setup.get('state'),
                'impulse': active_setup.get('impulse'),
                'avg_range': active_setup.get('avg_range'),
                'setup_quality_score': active_setup.get('setup_quality_score'),
                'setup_quality_tags': active_setup.get('setup_quality_tags'),
                'confirmation_tags': tags,
                'profile_key': f"{signal}_{active_setup.get('structure')}",
                'setup_age_seconds': round(time.time() - setup_started_at, 2) if setup_started_at else None,
                'retest_depth': round(depth, 2),
            },
            'result': 'open',
        })


def on_message(ws, message):
    global last_price
    try:
        data = json.loads(message)
        if 'price' not in data:
            return
        price = float(data['price'])
        print(f'💰 {price}')
        if last_price is None:
            last_price = price
            return
        if abs(price - last_price) < 0.05:
            return
        update_results(price)
        process(price)
        last_price = price
    except Exception as e:
        print('❌ Error:', e)


def on_open(ws):
    print('✅ WS Connected')
    ws.send(json.dumps({
        'action': 'subscribe',
        'params': {
            'symbols': 'XAU/USD',
            'type': 'price',
        },
    }))


def on_error(ws, error):
    print('⚠️ WS Error:', error)


def on_close(ws, code, msg):
    print('🔌 WS Closed')


def run_ws():
    global running
    while running:
        try:
            ws = websocket.WebSocketApp(
                f'wss://ws.twelvedata.com/v1/quotes/price?apikey={API_KEY}',
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            ws.run_forever()
        except Exception as e:
            print('❌ Reconnect Error:', e)
        if running:
            print('🔄 Reconnecting in 5s...')
            time.sleep(5)
