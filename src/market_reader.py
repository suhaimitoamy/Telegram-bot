from __future__ import annotations

from typing import Any


def format_price(value: float | None) -> str:
    if value is None:
        return "belum terbentuk"
    return f"{value:,.3f}"


def candle_body(candle: dict[str, float]) -> float:
    return abs(candle["close"] - candle["open"])


def candle_range(candle: dict[str, float]) -> float:
    return max(candle["high"] - candle["low"], 0.0001)


def upper_wick(candle: dict[str, float]) -> float:
    return candle["high"] - max(candle["open"], candle["close"])


def lower_wick(candle: dict[str, float]) -> float:
    return min(candle["open"], candle["close"]) - candle["low"]


def bounce_confirmed(
    last_candle: dict[str, float],
    prev_candle: dict[str, float],
    level: float,
    min_reclaim: float,
) -> bool:
    touched_level = last_candle["low"] <= level
    reclaimed_level = last_candle["close"] > level
    bullish_close = last_candle["close"] > last_candle["open"]
    strong_rejection = lower_wick(last_candle) > candle_body(last_candle)
    follow_through = last_candle["close"] > prev_candle["close"]
    enough_reclaim = (last_candle["close"] - level) >= min_reclaim

    return (
        touched_level
        and reclaimed_level
        and bullish_close
        and strong_rejection
        and follow_through
        and enough_reclaim
    )


def breakout_valid(
    last_candle: dict[str, float],
    prev_candle: dict[str, float],
    level: float,
    direction: str,
    min_body_ratio: float,
) -> bool:
    body = candle_body(last_candle)
    rng = candle_range(last_candle)
    body_ratio = body / rng
    momentum_ok = body > candle_body(prev_candle)

    if direction == "up":
        close_outside = last_candle["close"] > level
        bullish_body = last_candle["close"] > last_candle["open"]
        wick_ok = upper_wick(last_candle) < body
        return close_outside and bullish_body and wick_ok and momentum_ok and body_ratio >= min_body_ratio

    if direction == "down":
        close_outside = last_candle["close"] < level
        bearish_body = last_candle["close"] < last_candle["open"]
        wick_ok = lower_wick(last_candle) < body
        return close_outside and bearish_body and wick_ok and momentum_ok and body_ratio >= min_body_ratio

    return False


def rejection_confirmed(
    last_candle: dict[str, float],
    level: float,
    direction: str,
) -> bool:
    body = candle_body(last_candle)

    if direction == "upper":
        touched = last_candle["high"] >= level
        closed_back = last_candle["close"] < level
        bearish_close = last_candle["close"] < last_candle["open"]
        wick_reject = upper_wick(last_candle) > body
        return touched and closed_back and bearish_close and wick_reject

    if direction == "lower":
        touched = last_candle["low"] <= level
        closed_back = last_candle["close"] > level
        bullish_close = last_candle["close"] > last_candle["open"]
        wick_reject = lower_wick(last_candle) > body
        return touched and closed_back and bullish_close and wick_reject

    return False


def _major_levels(config: dict[str, Any]) -> list[float]:
    raw = config.get("levels", {})
    values: list[float] = []
    for key in ("lower_decision", "tp_mid", "upper_supply", "upper_breakout", "upper_extreme"):
        value = raw.get(key)
        if value is None:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return sorted(set(values))


def _next_major_level(price: float, config: dict[str, Any]) -> float | None:
    for level in _major_levels(config):
        if level > price:
            return level
    return None


def build_structure_event_read(event: dict[str, Any]) -> dict[str, str]:
    return {
        "state": event["state"],
        "message": event["message"],
    }


def build_live_market_read(
    price: float,
    structure: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, str]:
    logic = config["logic"]
    near_buffer = float(logic["near_buffer"])

    active_support = structure.get("active_support")
    active_resistance = structure.get("active_resistance")
    support_broken = bool(structure.get("support_broken"))
    resistance_broken = bool(structure.get("resistance_broken"))
    next_major = _next_major_level(price, config)

    if active_support is not None and abs(price - active_support) <= near_buffer:
        suffix = (
            f" Resistance aktif terdekat ada di {format_price(active_resistance)}."
            if active_resistance is not None
            else ""
        )
        return {
            "state": "support_zone_monitoring",
            "message": (
                f"Harga sedang menguji support aktif {format_price(active_support)}. "
                "Pantau apakah muncul rejection bullish yang valid atau justru candle close breakdown pada level ini."
                f"{suffix}"
            ),
        }

    if active_resistance is not None and abs(price - active_resistance) <= near_buffer:
        suffix = (
            f" Support aktif terdekat ada di {format_price(active_support)}."
            if active_support is not None
            else ""
        )
        return {
            "state": "resistance_zone_monitoring",
            "message": (
                f"Harga sedang menguji resistance aktif {format_price(active_resistance)}. "
                "Pantau apakah muncul rejection bearish yang valid atau justru candle close breakout di atas level ini."
                f"{suffix}"
            ),
        }

    if support_broken and active_resistance is not None and price < active_resistance:
        return {
            "state": "post_support_breakdown",
            "message": (
                f"Struktur masih bearish setelah breakdown support. Resistance hasil flip berada di {format_price(active_resistance)}, "
                f"sedangkan support aktif baru berada di {format_price(active_support)}."
            ),
        }

    if resistance_broken and active_support is not None and price > active_support:
        next_text = f" Resistance aktif baru dipantau di {format_price(active_resistance)}." if active_resistance is not None else ""
        return {
            "state": "post_resistance_breakout",
            "message": (
                f"Struktur masih bullish setelah breakout resistance. Support hasil flip berada di {format_price(active_support)}.{next_text}"
            ),
        }

    if active_support is not None and active_resistance is not None:
        return {
            "state": "neutral_structure",
            "message": (
                f"Harga masih bergerak di antara support aktif {format_price(active_support)} dan resistance aktif {format_price(active_resistance)}. "
                "Tunggu harga masuk ke salah satu level itu atau tunggu candle close yang memberi konfirmasi baru."
            ),
        }

    if next_major is not None:
        return {
            "state": "neutral_structure",
            "message": (
                f"Struktur aktif belum lengkap, tetapi level referensi berikutnya berada di {format_price(next_major)}. "
                "Tunggu pembentukan swing yang lebih jelas sebelum membaca market terlalu agresif."
            ),
        }

    return {
        "state": "neutral_structure",
        "message": "Struktur market belum cukup jelas. Tunggu candle close berikutnya untuk validasi support atau resistance aktif yang baru.",
    }
