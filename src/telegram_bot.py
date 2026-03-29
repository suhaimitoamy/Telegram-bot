from __future__ import annotations

from datetime import datetime

import requests

from src.config import get_env


def now_wita() -> str:
    return datetime.now().strftime("%H:%M WITA")


def _post(message: str) -> bool:
    bot_token = get_env("TELEGRAM_BOT_TOKEN")
    chat_id = get_env("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print("Telegram config missing")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        response = requests.post(
            url,
            json={"chat_id": chat_id, "text": message},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok", False):
            print(f"Telegram rejected message: {payload}")
            return False
        return True
    except Exception as exc:
        print(f"Telegram error: {exc}")
        return False


def send_status(text: str) -> bool:
    msg = f"ℹ️ BOT STATUS\n🕒 {now_wita()}\n{text}"
    return _post(msg)


def send_market_read(state: str, price: float, message: str) -> bool:
    msg = (
        "📡 MARKET READ\n"
        f"🕒 {now_wita()}\n"
        f"💰 Price: {price:,.3f}\n"
        f"🧠 State: {state}\n"
        f"📝 {message}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ Entry tetap manual. Tunggu konfirmasi market."
    )
    return _post(msg)
