from __future__ import annotations

from datetime import datetime

import requests

from src.config import get_env


STATE_LABELS = {
    "near_lower_range": "Dekat batas bawah range",
    "lower_bounce_confirmed": "Bounce bawah terkonfirmasi",
    "lower_breakdown_confirmed": "Breakdown bawah terkonfirmasi",
    "upper_supply_zone": "Masuk area supply atas",
    "upper_rejection_confirmed": "Rejection supply terkonfirmasi",
    "upper_breakout_watch": "Pantau breakout atas",
    "upper_breakout_confirmed": "Breakout atas terkonfirmasi",
    "extreme_upper_zone": "Area ekstrem atas",
    "neutral": "Range netral",
}


def now_wita() -> str:
    return datetime.now().strftime("%H:%M WITA")


def _pretty_state(state: str) -> str:
    return STATE_LABELS.get(state, state.replace("_", " ").title())


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
    msg = (
        "ℹ️ BOT STATUS\n"
        f"🕒 {now_wita()}\n"
        f"{text}"
    )
    return _post(msg)


def send_market_read(state: str, price: float, message: str) -> bool:
    msg = (
        "📡 MARKET READ\n"
        f"🕒 {now_wita()}\n"
        f"💰 Harga sekarang : {price:,.3f}\n"
        f"🧠 Kondisi market : {_pretty_state(state)}\n"
        "──────────────────\n"
        f"{message}\n"
        "──────────────────\n"
        "⚠️ Eksekusi tetap manual. Tunggu konfirmasi market."
    )
    return _post(msg)
