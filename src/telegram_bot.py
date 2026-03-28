import os
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
URL = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage' if BOT_TOKEN else None


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
