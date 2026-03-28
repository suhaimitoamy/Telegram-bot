import json
import os
import time

import websocket
from dotenv import load_dotenv

from src.market_engine import snapshot
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


def valid_entry(signal, price, previous_price):
    if previous_price is None:
        return False
    return True


def entry_confirmation(signal, price, previous_price, current_stall_count):
    if previous_price is None:
        return False
    if current_stall_count < 1:
        return False
    return True


def process(price):
    global last_setup_key, entry_triggered, current_area, active_setup
    global last_tick_price, stall_count

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
                print(f'📡 SETUP {signal} | Area {entry_low}-{entry_high}')
                send_setup(data)
                return
            active_setup = data

    if not current_area or not active_setup:
        return

    signal_data = active_setup.get('signal', {})
    signal = signal_data.get('signal')
    if not signal or signal == 'NO TRADE':
        return

    low, high = current_area
    mid = (low + high) / 2
    if last_tick_price is not None:
        diff = abs(price - last_tick_price)
        stall_count = stall_count + 1 if diff < 0.3 else 0
    last_tick_price = price
    if not entry_triggered and low <= price <= high:
        if abs(price - mid) > ((high - low) * 0.6):
            print(f'[ENTRY BLOCKED] edge area | price={price} mid={mid} low={low} high={high}')
            return
        if not valid_entry(signal, price, last_price):
            print(f'[ENTRY BLOCKED] valid_entry failed | signal={signal} price={price} last_price={last_price}')
            return
        if not entry_confirmation(signal, price, last_price, stall_count):
            print(
                f'[ENTRY BLOCKED] confirmation failed | signal={signal} price={price} '
                f'last_price={last_price} stall={stall_count}'
            )
            return
        entry_triggered = True
        print(f'🚀 ENTRY TRIGGERED {signal} @ {price}')
        send_entry(active_setup)
        entry = round(mid, 2)
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
