from __future__ import annotations

from datetime import datetime

import requests

from src.config import get_env


STATE_LABELS = {
    "support_zone_monitoring": "Pantau support aktif",
    "resistance_zone_monitoring": "Pantau resistance aktif",
    "support_bounce_confirmed": "Pantulan valid dari support aktif",
    "support_breakdown_confirmed": "Support aktif ditembus valid",
    "post_support_breakdown": "Struktur bearish pasca-breakdown",
    "resistance_rejection_confirmed": "Penolakan valid dari resistance aktif",
    "resistance_breakout_confirmed": "Resistance aktif ditembus valid",
    "post_resistance_breakout": "Struktur bullish pasca-breakout",
    "neutral_structure": "Struktur netral",
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


def send_market_closed(text: str) -> bool:
    msg = (
        "⏸️ MARKET CLOSED\n"
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
        "⚠️ Keputusan entry tetap manual. Tunggu konfirmasi market."
    )
    return _post(msg)


def send_session_info(title: str, text: str) -> bool:
    msg = (
        f"🕒 {title}\n"
        f"🕒 {now_wita()}\n"
        "──────────────────\n"
        f"{text}"
    )
    return _post(msg)


def send_liquidity_alert(title: str, text: str) -> bool:
    msg = (
        f"💧 {title}\n"
        f"🕒 {now_wita()}\n"
        "──────────────────\n"
        f"{text}"
    )
    return _post(msg)


def send_caution(text: str) -> bool:
    msg = (
        "⚠️ MARKET CAUTION\n"
        f"🕒 {now_wita()}\n"
        "──────────────────\n"
        f"{text}"
    )
    return _post(msg)


def send_news_alert(title: str, text: str) -> bool:
    msg = (
        f"📰 {title}\n"
        f"🕒 {now_wita()}\n"
        "──────────────────\n"
        f"{text}"
    )
    return _post(msg)


def send_news_result(
    event_name: str,
    before: str,
    forecast: str,
    actual: str,
    verdict: str,
    reason: str,
) -> bool:
    msg = (
        "🟥 HIGH IMPACT NEWS\n"
        f"🕒 {now_wita()}\n"
        "──────────────────\n"
        f"Event    : {event_name}\n"
        f"Before   : {before or '-'}\n"
        f"Forecast : {forecast or '-'}\n"
        f"Actual   : {actual or '-'}\n\n"
        f"Dampak awal : {verdict}\n"
        f"Alasan      : {reason}"
    )
    return _post(msg)
