from __future__ import annotations

from datetime import datetime
from typing import Any


def parse_release_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M")


def parse_number(value: str) -> float | None:
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


def evaluate_gold_impact(kind: str, forecast: str, actual: str) -> tuple[str, str]:
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


def build_pre_news_message(event: dict[str, Any], minutes_left: int) -> str:
    impact = event.get("impact", "high").upper()
    return (
        f"{minutes_left} menit lagi rilis {event['name']} ({impact}).\n"
        f"Before   : {event.get('before') or '-'}\n"
        f"Forecast : {event.get('forecast') or '-'}\n"
        "Hindari entry impulsif sebelum data keluar."
    )


def build_post_news_message(event: dict[str, Any], minutes_after: int) -> str:
    return (
        f"{minutes_after} menit setelah rilis {event['name']}.\n"
        "Hindari mengejar lonjakan pertama. Tunggu struktur market kembali jelas."
    )


def process_news_events(now: datetime, config: dict[str, Any], sent_event_keys: set[str]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    settings = config.get("news_settings", {})
    events = config.get("news_events", [])

    for event in events:
        release_time = parse_release_time(event["release_time"])
        delta_minutes = int((release_time - now).total_seconds() // 60)
        after_minutes = int((now - release_time).total_seconds() // 60)
        event_id = event.get("id", event["name"])

        for minute in settings.get("pre_alert_minutes", []):
            if delta_minutes == minute:
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

        actual = str(event.get("actual", "")).strip()
        if delta_minutes == 0:
            key = f"news_release_{event_id}"
            if key not in sent_event_keys:
                sent_event_keys.add(key)
                if actual:
                    verdict, reason = evaluate_gold_impact(event.get("kind", ""), event.get("forecast", ""), actual)
                    results.append(
                        {
                            "kind": "result",
                            "event_name": event["name"],
                            "before": event.get("before", ""),
                            "forecast": event.get("forecast", ""),
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
                            "message": f"{event['name']} sedang dirilis sekarang. Tunggu angka actual untuk membaca dampak awal ke gold.",
                        }
                    )

        if actual and after_minutes in settings.get("post_alert_minutes", []):
            key = f"news_post_{event_id}_{after_minutes}"
            if key not in sent_event_keys:
                sent_event_keys.add(key)
                results.append(
                    {
                        "kind": "pre_alert",
                        "title": "POST-NEWS CAUTION",
                        "message": build_post_news_message(event, after_minutes),
                    }
                )

    return results
