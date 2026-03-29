from __future__ import annotations

from datetime import datetime


SESSION_ORDER = ["asia", "pre_london", "london", "pre_new_york", "new_york"]


SESSION_LABELS = {
    "asia": "Asia",
    "pre_london": "Pre-London",
    "london": "London",
    "pre_new_york": "Pre-New York",
    "new_york": "New York",
}


def parse_hhmm(value: str) -> int:
    hour, minute = value.split(":")
    return (int(hour) * 60) + int(minute)


def minute_of_day(dt: datetime) -> int:
    return (dt.hour * 60) + dt.minute


def in_window(current_minute: int, start_minute: int, end_minute: int) -> bool:
    if start_minute <= end_minute:
        return start_minute <= current_minute < end_minute
    return current_minute >= start_minute or current_minute < end_minute


def is_market_open(now: datetime, market_hours: dict) -> bool:
    weekday = now.weekday()
    current_minute = minute_of_day(now)
    monday_open = parse_hhmm(market_hours.get("monday_open", "06:00"))

    if weekday == 5:
        return False
    if weekday == 6:
        return False
    if weekday == 0 and current_minute < monday_open:
        return False
    return True


def get_current_session(now: datetime, sessions: dict) -> str | None:
    current_minute = minute_of_day(now)
    for name in SESSION_ORDER:
        item = sessions.get(name)
        if not item:
            continue
        start_minute = parse_hhmm(item["start"])
        end_minute = parse_hhmm(item["end"])
        if in_window(current_minute, start_minute, end_minute):
            return name
    return None


def get_session_label(name: str | None, sessions: dict) -> str:
    if not name:
        return "Di luar sesi utama"
    return sessions.get(name, {}).get("label", SESSION_LABELS.get(name, name))


def minutes_until_session(now: datetime, sessions: dict, session_name: str) -> int | None:
    item = sessions.get(session_name)
    if not item:
        return None
    current_minute = minute_of_day(now)
    target_minute = parse_hhmm(item["start"])
    if target_minute >= current_minute:
        return target_minute - current_minute
    return (24 * 60) - current_minute + target_minute


def session_transition_message(session_name: str, sessions: dict) -> tuple[str, str]:
    label = get_session_label(session_name, sessions)

    if session_name == "asia":
        return (
            "SESSION INFO",
            f"Sesi {label} sedang berjalan. Fokus utama: amati pembentukan high dan low sesi Asia sebagai referensi likuiditas.",
        )
    if session_name == "pre_london":
        return (
            "SESSION INFO",
            f"Sesi {label} dimulai. Waspadai Judas swing atau sapuan likuiditas sebelum arah London menjadi jelas.",
        )
    if session_name == "london":
        return (
            "SESSION CHANGE",
            f"Sesi {label} dimulai. Perhatikan apakah harga menyapu high/low Asia sebelum bergerak ke arah utama.",
        )
    if session_name == "pre_new_york":
        return (
            "SESSION INFO",
            f"Sesi {label} dimulai. Waspadai perubahan tempo market menjelang pembukaan New York.",
        )
    if session_name == "new_york":
        return (
            "SESSION CHANGE",
            f"Sesi {label} dimulai. Perhatikan volatilitas yang meningkat dan hindari entry impulsif tanpa konfirmasi.",
        )
    return (
        "SESSION INFO",
        f"Sesi {label} sedang berjalan.",
    )
