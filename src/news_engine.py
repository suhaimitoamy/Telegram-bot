from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

import requests

from src.config import get_env


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text == "":
        return None
    keep = []
    for ch in text:
        if ch.isdigit() or ch in ".-":
            keep.append(ch)
    cleaned = "".join(keep)
    if cleaned in {"", ".", "-", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def evaluate_gold_impact(kind: str, forecast: Any, actual: Any, event_name: str = "") -> tuple[str, str]:
    event_lower = event_name.lower()
    if "unemployment" in event_lower:
        kind = "unemployment"
    elif any(word in event_lower for word in ["cpi", "pce", "ppi", "inflation"]):
        kind = "inflation"
    elif any(word in event_lower for word in ["non farm", "non-farm", "nfp", "payroll", "retail sales", "gdp"]):
        kind = "jobs"
    elif "fomc" in event_lower or "interest rate" in event_lower or "fed" in event_lower:
        kind = "hawkish_usd"

    forecast_num = parse_number(forecast)
    actual_num = parse_number(actual)

    if forecast_num is None or actual_num is None:
        return (
            "Perlu dibaca manual",
            "Data angka belum cukup jelas untuk dinilai otomatis. Baca hasil rilis secara manual.",
        )

    if kind in {"inflation", "growth", "jobs", "hawkish_usd"}:
        if actual_num > forecast_num:
            return (
                "Bad for gold",
                "Actual lebih tinggi dari forecast. Ini cenderung mendukung USD dan menekan emas.",
            )
        if actual_num < forecast_num:
            return (
                "Good for gold",
                "Actual lebih rendah dari forecast. Ini cenderung melemahkan USD dan mendukung emas.",
            )
        return (
            "Netral untuk gold",
            "Actual sama dengan forecast. Reaksi market perlu dibaca dari konteks harga.",
        )

    if kind in {"unemployment", "dovish_usd"}:
        if actual_num > forecast_num:
            return (
                "Good for gold",
                "Actual lebih tinggi dari forecast. Ini cenderung menekan USD dan mendukung emas.",
            )
        if actual_num < forecast_num:
            return (
                "Bad for gold",
                "Actual lebih rendah dari forecast. Ini cenderung mendukung USD dan menekan emas.",
            )
        return (
            "Netral untuk gold",
            "Actual sama dengan forecast. Reaksi market perlu dibaca dari konteks harga.",
        )

    return (
        "Perlu dibaca manual",
        "Jenis news belum punya rule otomatis. Baca hasil rilis secara manual.",
    )


def parse_te_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is not None:
            return dt.astimezone().replace(tzinfo=None)
        return dt
    except ValueError:
        pass

    try:
        if text.startswith("/Date(") and text.endswith(")/"):
            millis = int(text[6:-2])
            return datetime.fromtimestamp(millis / 1000)
    except Exception:
        return None
    return None


def event_matches_filters(event: dict[str, Any], settings: dict[str, Any]) -> bool:
    currencies = settings.get("currencies", ["USD"])
    if currencies and str(event.get("Currency", "")).upper() not in {c.upper() for c in currencies}:
        return False

    importance = str(event.get("Importance", "")).strip().lower()
    if importance not in {"3", "high", "3.0"}:
        return False

    event_name = str(event.get("Event", ""))
    keywords = settings.get("keywords", [])
    if keywords and not any(keyword.lower() in event_name.lower() for keyword in keywords):
        return False

    return True


def fetch_tradingeconomics_calendar(now: datetime, settings: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    poll_seconds = int(settings.get("poll_seconds", 60))
    last_fetch_at = state.get("last_fetch_at")
    cached_events = state.get("cached_events", [])
    if last_fetch_at and (now - last_fetch_at).total_seconds() < poll_seconds:
        return cached_events

    api_key = get_env("TRADING_ECONOMICS_API_KEY")
    if not api_key:
        return cached_events

    try:
        response = requests.get(
            "https://api.tradingeconomics.com/calendar",
            params={"c": api_key, "f": "json"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            cached_events = payload
            state["cached_events"] = cached_events
            state["last_fetch_at"] = now
    except Exception as exc:
        print(f"TradingEconomics fetch error: {exc}")

    return cached_events


def build_pre_news_message(event: dict[str, Any], minutes_left: int) -> str:
    return (
        f"{minutes_left} menit lagi rilis {event['Event']} (USD / HIGH).\n"
        f"Before   : {event.get('Previous') or '-'}\n"
        f"Forecast : {event.get('Forecast') or '-'}\n"
        "Hindari entry impulsif sebelum data keluar."
    )


def build_post_news_message(event: dict[str, Any], minutes_after: int) -> str:
    return (
        f"{minutes_after} menit setelah rilis {event['Event']}.\n"
        "Hindari mengejar lonjakan pertama. Tunggu struktur market kembali jelas."
    )


def process_news_events(now: datetime, config: dict[str, Any], sent_event_keys: set[str], state: dict[str, Any]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    settings = config.get("news_settings", {})
    if settings.get("provider") != "tradingeconomics":
        return results

    events = fetch_tradingeconomics_calendar(now, settings, state)
    lookback = int(settings.get("lookback_hours", 6))
    lookahead = int(settings.get("lookahead_hours", 24))

    for event in events:
        if not event_matches_filters(event, settings):
            continue

        release_time = parse_te_datetime(event.get("Date") or event.get("ReferenceDate") or event.get("LastUpdate"))
        if release_time is None:
            continue

        if release_time < now - timedelta(hours=lookback) or release_time > now + timedelta(hours=lookahead):
            continue

        event_id = str(event.get("CalendarId") or f"{event.get('Event','event')}_{release_time.isoformat()}")
        seconds_to_release = (release_time - now).total_seconds()
        minutes_to_release = math.ceil(seconds_to_release / 60) if seconds_to_release > 0 else 0
        minutes_after_release = math.floor((now - release_time).total_seconds() / 60) if now >= release_time else -1

        for minute in settings.get("pre_alert_minutes", []):
            if minutes_to_release == minute:
                key = f"news_pre_{event_id}_{minute}"
                if key not in sent_event_keys:
                    sent_event_keys.add(key)
                    results.append(
                        {
                            "kind": "pre_alert",
                            "title": "NEWS ALERT",
                            "message": build_pre_news_message(event, minute),
                        }
                    )

        actual = str(event.get("Actual") or "").strip()
        if minutes_to_release == 0:
            key = f"news_release_{event_id}"
            if key not in sent_event_keys:
                sent_event_keys.add(key)
                if actual:
                    verdict, reason = evaluate_gold_impact(
                        str(event.get("Category") or ""),
                        event.get("Forecast"),
                        actual,
                        str(event.get("Event") or ""),
                    )
                    results.append(
                        {
                            "kind": "result",
                            "event_name": str(event.get("Event") or "Unknown Event"),
                            "before": str(event.get("Previous") or ""),
                            "forecast": str(event.get("Forecast") or ""),
                            "actual": actual,
                            "verdict": verdict,
                            "reason": reason,
                        }
                    )
                else:
                    results.append(
                        {
                            "kind": "pre_alert",
                            "title": "HIGH IMPACT NEWS",
                            "message": f"{event.get('Event','News')} sedang dirilis sekarang. Tunggu angka actual untuk membaca dampak awal ke gold.",
                        }
                    )

        if actual and minutes_after_release in settings.get("post_alert_minutes", []):
            key = f"news_post_{event_id}_{minutes_after_release}"
            if key not in sent_event_keys:
                sent_event_keys.add(key)
                results.append(
                    {
                        "kind": "pre_alert",
                        "title": "POST-NEWS CAUTION",
                        "message": build_post_news_message(event, minutes_after_release),
                    }
                )

    return results
