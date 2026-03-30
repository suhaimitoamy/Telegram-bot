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
    structure_state: dict[str, bool] | None = None,
) -> dict[str, str]:
    levels = config["levels"]
    logic = config["logic"]
    lower_decision = levels["lower_decision"]
    upper_supply = levels["upper_supply"]
    upper_breakout = levels["upper_breakout"]
    upper_extreme = levels["upper_extreme"]

    if structure_state is None:
        structure_state = {
            "lower_decision_flipped": False,
            "upper_breakout_flipped": False,
        }

    lower_flipped = structure_state.get("lower_decision_flipped", False)
    upper_breakout_flipped = structure_state.get("upper_breakout_flipped", False)

    if bounce_confirmed(last_candle, prev_candle, lower_decision, logic["bounce_min_reclaim"]):
        return {
            "state": "lower_bounce_confirmed",
            "message": (
                f"Harga berhasil bertahan di area support minor {format_price(lower_decision)} dan mulai memantul naik. "
                f"Selama harga tetap di atas level ini, peluang naik masih layak diperhatikan."
            ),
        }

    if breakout_valid(last_candle, prev_candle, lower_decision, "down", logic["min_body_ratio"]):
        return {
            "state": "lower_breakdown_confirmed",
            "message": (
                f"Harga menembus support minor {format_price(lower_decision)} dengan penembusan yang valid. "
                f"Level ini sekarang diperlakukan sebagai resistance sampai ada reclaim yang valid ke atas. "
                f"Selama harga tetap di bawah level ini, tekanan turun masih dominan."
            ),
        }

    if rejection_confirmed(last_candle, upper_supply, "upper"):
        return {
            "state": "upper_rejection_confirmed",
            "message": (
                f"Harga menyentuh resistance minor {format_price(upper_supply)} lalu ditolak turun. "
                f"Selama harga belum mampu bertahan di atas level ini, area atas masih rawan tekanan jual."
            ),
        }

    if breakout_valid(last_candle, prev_candle, upper_breakout, "up", logic["min_body_ratio"]):
        return {
            "state": "upper_breakout_confirmed",
            "message": (
                f"Harga berhasil menembus resistance penting {format_price(upper_breakout)} dengan penembusan yang valid. "
                f"Level ini sekarang diperlakukan sebagai support selama harga bertahan di atasnya."
            ),
        }

    near_buffer = logic["near_buffer"]

    if lower_flipped:
        if abs(price - lower_decision) <= near_buffer:
            return {
                "state": "lower_flip_resistance_watch",
                "message": (
                    f"Support minor {format_price(lower_decision)} sudah break valid sebelumnya dan sekarang berperan sebagai resistance minor. "
                    f"Jika harga gagal reclaim dan bertahan di atas level ini, tekanan turun masih layak diperhatikan."
                ),
            }

        if price < lower_decision:
            return {
                "state": "lower_flip_bearish_hold",
                "message": (
                    f"Harga masih bertahan di bawah bekas support minor {format_price(lower_decision)}. "
                    f"Karena level ini sudah break valid, area tersebut sekarang dibaca sebagai resistance. "
                    f"Selama harga tetap di bawahnya, bias jangka pendek masih bearish."
                ),
            }

    if abs(price - lower_decision) <= near_buffer or market_zone(price, levels) == "near_lower_range":
        return {
            "state": "near_lower_range",
            "message": (
                f"Harga sedang mendekati area support minor {format_price(lower_decision)}. "
                f"Jika level ini bertahan, harga berpeluang memantul naik. "
                f"Jika level ini ditembus, tekanan turun bisa berlanjut.\n\n"
                f"Resistance minor terdekat berada di {format_price(upper_supply)}, "
                f"sedangkan {format_price(upper_breakout)} adalah level penting yang perlu ditembus untuk membuka peluang naik yang lebih kuat."
            ),
        }

    if abs(price - upper_supply) <= near_buffer or market_zone(price, levels) == "at_upper_supply":
        return {
            "state": "upper_supply_zone",
            "message": (
                f"Harga sedang mendekati resistance minor {format_price(upper_supply)}. "
                f"Jika gagal menembus area ini, harga berisiko tertahan atau berbalik turun. "
                f"Jika mampu menembus dengan kuat, target perhatian berikutnya adalah {format_price(upper_breakout)}."
            ),
        }

    if abs(price - upper_breakout) <= near_buffer or market_zone(price, levels) == "breakout_zone":
        if upper_breakout_flipped and price > upper_breakout:
            return {
                "state": "upper_breakout_support_hold",
                "message": (
                    f"Harga masih bertahan di atas bekas resistance penting {format_price(upper_breakout)}. "
                    f"Karena breakout valid sudah terjadi, level ini sekarang diperlakukan sebagai support. "
                    f"Selama harga tetap di atasnya, peluang naik masih terbuka."
                ),
            }

        return {
            "state": "upper_breakout_watch",
            "message": (
                f"Harga sedang mendekati resistance penting {format_price(upper_breakout)}. "
                f"Kenaikan baru dianggap kuat jika candle mampu ditutup jelas di atas level ini, bukan hanya lewat sesaat."
            ),
        }

    if price >= upper_extreme:
        return {
            "state": "extreme_upper_zone",
            "message": (
                f"Harga sudah masuk area atas {format_price(upper_extreme)}. "
                f"Zona ini rawan pergerakan berlebihan, jadi hindari mengejar harga tanpa konfirmasi yang jelas."
            ),
        }

    return {
        "state": "neutral",
        "message": (
            f"Harga masih bergerak di antara support minor {format_price(lower_decision)} dan resistance minor {format_price(upper_supply)}. "
            f"Level penting di atas berada di {format_price(upper_breakout)}."
        ),
    }
