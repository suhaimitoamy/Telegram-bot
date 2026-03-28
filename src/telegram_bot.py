from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = None
CHAT_ID = None
URL = None


def _reload_env():
    global BOT_TOKEN, CHAT_ID, URL
    import os

    BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
    URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage' if BOT_TOKEN else None


_reload_env()


def now():
    return datetime.now().strftime('%H:%M WIB')


def _post(message):
    if not URL or not CHAT_ID:
        print('Telegram config missing')
        return
    try:
        requests.post(URL, json={'chat_id': CHAT_ID, 'text': message}, timeout=10)
    except Exception as e:
        print('Telegram error:', e)


def _fmt(value):
    if isinstance(value, float):
        return f'{value:.2f}'
    return str(value)


def send_setup(data):
    sig = data.get('signal', {})
    if sig.get('signal') == 'NO TRADE':
        return
    msg = f"""
📡 SETUP DETECTED
🕒 {now()}
📍 Direction : {sig['signal']}
📦 Area      : {sig['entry_low']} - {sig['entry_high']}
━━━━━━━━━━━━━━━━━━
📈 Bias  : {data['structure']}
⚡ Break : {data['break']}
🧠 State : {data['state']}
⏳ Tunggu price masuk area
"""
    _post(msg)


def send_entry(data):
    sig = data.get('signal', {})
    if sig.get('signal') == 'NO TRADE':
        return
    msg = f"""
🚀 ENTRY TRIGGER
🕒 {now()}
📍 Signal : {sig['signal']}
📦 Area   : {sig['entry_low']} - {sig['entry_high']}
🛑 SL     : {sig['sl']}
🎯 TP     : {sig['tp']}
━━━━━━━━━━━━━━━━━━
📈 Bias  : {data['structure']}
⚡ Break : {data['break']}
⚠️ Harga sudah masuk area
"""
    _post(msg)


def send_news(text, news_type='MARKET', indo=None):
    if news_type == 'ECONOMIC':
        header = '🟥 ECONOMIC NEWS'
    elif news_type == 'GEOPOLITICAL':
        header = '🌍 GEOPOLITICAL NEWS'
    else:
        header = '📰 MARKET NEWS'
    body = f"{header}\n🕒 {now()}\n{text}"
    if indo:
        body += f"\n🇮🇩 {indo}"
    _post(body)


def send_status_alert(text):
    _post(f"ℹ️ NOTIFIER STATUS\n🕒 {now()}\n{text}")


def send_break_alert(event):
    direction = 'Bullish' if event.get('direction') == 'UP' else 'Bearish'
    msg = (
        f"📡 MARKET STRUCTURE BREAK\n"
        f"🕒 {now()}\n"
        f"📍 Symbol     : XAU/USD\n"
        f"📈 Bias       : {event.get('bias')}\n"
        f"🧭 Direction  : {direction}\n"
        f"🔓 Broken Lvl : {_fmt(event.get('level'))}\n"
        f"💰 Close      : {_fmt(event.get('close'))}\n"
        f"📦 Retest Zone: {_fmt(event.get('retest_low'))} - {_fmt(event.get('retest_high'))}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Status : swing broken, waiting retest or direct continuation\n"
        f"Note   : market may continue without clean retest"
    )
    _post(msg)


def send_retest_alert(event):
    direction = 'Bullish' if event.get('direction') == 'UP' else 'Bearish'
    msg = (
        f"🔁 RETEST UPDATE\n"
        f"🕒 {now()}\n"
        f"📍 Symbol     : XAU/USD\n"
        f"🧭 Direction  : {direction}\n"
        f"🎯 Key Level  : {_fmt(event.get('level'))}\n"
        f"💰 Candle Cls : {_fmt(event.get('close'))}\n"
        f"📦 Zone       : {_fmt(event.get('retest_low'))} - {_fmt(event.get('retest_high'))}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Status : retest in progress\n"
        f"Watch  : apakah level dipertahankan atau break gagal"
    )
    _post(msg)


def send_continuation_alert(event):
    direction = 'Bullish' if event.get('direction') == 'UP' else 'Bearish'
    msg = (
        f"🚦 NO-RETEST CONTINUATION\n"
        f"🕒 {now()}\n"
        f"📍 Symbol     : XAU/USD\n"
        f"🧭 Direction  : {direction}\n"
        f"🔓 Broken Lvl : {_fmt(event.get('level'))}\n"
        f"💰 Close      : {_fmt(event.get('close'))}\n"
        f"📏 Extension  : {_fmt(event.get('extension'))}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Status : continuation without clean retest\n"
        f"Warning: avoid chasing after impulsive move"
    )
    _post(msg)


def send_failure_alert(event):
    direction = 'Bullish' if event.get('direction') == 'UP' else 'Bearish'
    msg = (
        f"⚠️ BREAK FAILURE\n"
        f"🕒 {now()}\n"
        f"📍 Symbol     : XAU/USD\n"
        f"🧭 Direction  : {direction}\n"
        f"🎯 Key Level  : {_fmt(event.get('level'))}\n"
        f"💰 Close      : {_fmt(event.get('close'))}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Status : breakout gagal dipertahankan\n"
        f"Note   : structure needs reset before next alert"
    )
    _post(msg)
