from __future__ import annotations

from typing import Any


def format_price(value: float) -> str:
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


def market_zone(price: float, levels: dict[str, float]) -> str:
    if price <= levels["lower_decision"]:
        return "at_lower_decision"
    if levels["lower_decision"] < price < levels["tp_mid"]:
        return "near_lower_range"
    if levels["tp_mid"] <= price < levels["upper_supply"]:
        return "mid_range"
    if levels["upper_supply"] <= price < levels["upper_breakout"]:
        return "at_upper_supply"
    if levels["upper_breakout"] <= price < levels["upper_extreme"]:
        return "breakout_zone"
    if price >= levels["upper_extreme"]:
        return "extreme_upper_zone"
    return "neutral"


def build_market_read(
    price: float,
    last_candle: dict[str, float],
    prev_candle: dict[str, float],
    config: dict[str, Any],
) -> dict[str, str]:
    levels = config["levels"]
    logic = config["logic"]
    lower_decision = levels["lower_decision"]
    upper_supply = levels["upper_supply"]
    upper_breakout = levels["upper_breakout"]
    upper_extreme = levels["upper_extreme"]

    if bounce_confirmed(last_candle, prev_candle, lower_decision, logic["bounce_min_reclaim"]):
        return {
            "state": "lower_bounce_confirmed",
            "message": (
                f"Market sedang menguji support {format_price(lower_decision)}. "
                f"Level bawah bertahan dan bounce terkonfirmasi. "
                f"Skenario aktif: buy bounce selama harga bertahan di atas {format_price(lower_decision)}."
            ),
        }

    if breakout_valid(last_candle, prev_candle, lower_decision, "down", logic["min_body_ratio"]):
        return {
            "state": "lower_breakdown_confirmed",
            "message": (
                f"Market menembus support {format_price(lower_decision)} dengan breakout valid. "
                f"Skenario aktif: sell continuation selama harga tetap di bawah {format_price(lower_decision)}."
            ),
        }

    if rejection_confirmed(last_candle, upper_supply, "upper"):
        return {
            "state": "upper_rejection_confirmed",
            "message": (
                f"Market sedang menguji supply {format_price(upper_supply)} dan rejection terkonfirmasi. "
                f"Skenario aktif: sell reaction selama harga gagal bertahan di atas {format_price(upper_supply)}."
            ),
        }

    if breakout_valid(last_candle, prev_candle, upper_breakout, "up", logic["min_body_ratio"]):
        return {
            "state": "upper_breakout_confirmed",
            "message": (
                f"Market berhasil menembus {format_price(upper_breakout)} dengan breakout valid. "
                f"Skenario aktif: buy breakout selama harga bertahan di atas {format_price(upper_breakout)}."
            ),
        }

    near_buffer = logic["near_buffer"]
    if abs(price - lower_decision) <= near_buffer or market_zone(price, levels) == "near_lower_range":
        return {
            "state": "near_lower_range",
            "message": (
                f"Market sedang berada dekat batas bawah range. "
                f"Area bawah {format_price(lower_decision)} adalah level keputusan: "
                f"bertahan = buy bounce, jebol = sell continuation. "
                f"Area atas {format_price(upper_supply)} adalah supply sell, "
                f"sedangkan {format_price(upper_breakout)} adalah trigger breakout buy bila tertembus valid."
            ),
        }

    if abs(price - upper_supply) <= near_buffer or market_zone(price, levels) == "at_upper_supply":
        return {
            "state": "upper_supply_zone",
            "message": (
                f"Area atas {format_price(upper_supply)} adalah supply sell. "
                f"Selama belum ada breakout valid ke atas, zona ini tetap layak dipantau sebagai area reaksi turun. "
                f"Trigger breakout buy berada di {format_price(upper_breakout)}."
            ),
        }

    if abs(price - upper_breakout) <= near_buffer or market_zone(price, levels) == "breakout_zone":
        return {
            "state": "upper_breakout_watch",
            "message": (
                f"Level {format_price(upper_breakout)} adalah trigger breakout buy. "
                f"Buy breakout hanya valid jika candle close kuat di atas level ini, "
                f"bukan sekadar wick atau spike sesaat."
            ),
        }

    if price >= upper_extreme:
        return {
            "state": "extreme_upper_zone",
            "message": (
                f"Harga sudah mencapai area ekstrem atas {format_price(upper_extreme)}. "
                f"Zona ini rawan overextension, jadi tunggu reaksi market dengan disiplin dan jangan mengejar candle."
            ),
        }

    return {
        "state": "neutral",
        "message": (
            f"Market masih berada di dalam range. "
            f"Support keputusan: {format_price(lower_decision)}. "
            f"Supply atas: {format_price(upper_supply)}. "
            f"Trigger breakout buy: {format_price(upper_breakout)}."
        ),
    }
