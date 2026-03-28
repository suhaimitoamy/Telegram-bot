import json
import os
import time
from datetime import datetime

import websocket
from dotenv import load_dotenv

from src.structure_notifier import update_runtime_with_tick
from src.telegram_bot import (
    send_break_alert,
    send_continuation_alert,
    send_failure_alert,
    send_retest_alert,
    send_status_alert,
)

load_dotenv()
API_KEY = os.getenv('TWELVE_API_KEY')

runtime_state = None
running = True


def dispatch_event(event):
    event_type = event.get('type')
    if event_type == 'status':
        send_status_alert(event.get('message', 'Notifier status update'))
    elif event_type == 'swing_break':
        send_break_alert(event)
    elif event_type == 'retest_watch':
        send_retest_alert(event)
    elif event_type == 'continuation_no_retest':
        send_continuation_alert(event)
    elif event_type == 'break_failed':
        send_failure_alert(event)


def on_message(ws, message):
    global runtime_state
    try:
        data = json.loads(message)
        if 'price' not in data:
            return
        price = float(data['price'])
        tick_dt = datetime.now()
        events, runtime_state = update_runtime_with_tick(runtime_state, price, tick_dt)
        for event in events:
            print(f"[EVENT] {event['type']} | {event}")
            dispatch_event(event)
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
