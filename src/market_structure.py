from __future__ import annotations

from typing import Any

from src.market_reader import bounce_confirmed, breakout_valid, rejection_confirmed


def _logic(config: dict[str, Any], key: str, default: float | int) -> float | int:
    return config.get("logic", {}).get(key, default)


def structure_epsilon(config: dict[str, Any]) -> float:
    min_tick_change = float(_logic(config, "min_tick_change", 0.1))
    return max(min_tick_change * 2.0, 0.25)


def _seed_levels(config: dict[str, Any]) -> list[float]:
    levels = config.get("levels", {})
    values: list[float] = []
    for value in levels.values():
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return sorted(set(values))


def _is_pivot_low(candles: list[dict[str, float]], index: int, width: int) -> bool:
    level = candles[index]["low"]
    left = candles[index - width:index]
    right = candles[index + 1:index + width + 1]
    if len(left) < width or len(right) < width:
        return False
    return all(level <= item["low"] for item in left + right)


def _is_pivot_high(candles: list[dict[str, float]], index: int, width: int) -> bool:
    level = candles[index]["high"]
    left = candles[index - width:index]
    right = candles[index + 1:index + width + 1]
    if len(left) < width or len(right) < width:
        return False
    return all(level >= item["high"] for item in left + right)


def _pivot_lows(candles: list[dict[str, float]], config: dict[str, Any]) -> list[tuple[int, float]]:
    width = int(_logic(config, "pivot_width", 2))
    pivots: list[tuple[int, float]] = []
    for index in range(width, len(candles) - width):
        if _is_pivot_low(candles, index, width):
            pivots.append((index, candles[index]["low"]))
    return pivots


def _pivot_highs(candles: list[dict[str, float]], config: dict[str, Any]) -> list[tuple[int, float]]:
    width = int(_logic(config, "pivot_width", 2))
    pivots: list[tuple[int, float]] = []
    for index in range(width, len(candles) - width):
        if _is_pivot_high(candles, index, width):
            pivots.append((index, candles[index]["high"]))
    return pivots


def _recent_window(candles: list[dict[str, float]], config: dict[str, Any]) -> list[dict[str, float]]:
    lookback = int(_logic(config, "structure_lookback", 80))
    return candles[-lookback:]


def _nearest_level_below(values: list[float], price: float, epsilon: float) -> float | None:
    choices = [value for value in values if value < price - epsilon]
    if not choices:
        return None
    return max(choices)


def _nearest_level_above(values: list[float], price: float, epsilon: float) -> float | None:
    choices = [value for value in values if value > price + epsilon]
    if not choices:
        return None
    return min(choices)


def _nearest_pivot_support(
    candles: list[dict[str, float]],
    price: float,
    config: dict[str, Any],
    excluded_level: float | None = None,
) -> float | None:
    epsilon = structure_epsilon(config)
    candidates: list[float] = []
    for _, level in _pivot_lows(_recent_window(candles, config), config):
        if level >= price - epsilon:
            continue
        if excluded_level is not None and abs(level - excluded_level) <= epsilon:
            continue
        candidates.append(level)
    if candidates:
        return max(candidates)

    fallback = [item["low"] for item in _recent_window(candles, config) if item["low"] < price - epsilon]
    if excluded_level is not None:
        fallback = [level for level in fallback if abs(level - excluded_level) > epsilon]
    if fallback:
        return max(fallback)
    return None


def _nearest_pivot_resistance(
    candles: list[dict[str, float]],
    price: float,
    config: dict[str, Any],
    excluded_level: float | None = None,
) -> float | None:
    epsilon = structure_epsilon(config)
    candidates: list[float] = []
    for _, level in _pivot_highs(_recent_window(candles, config), config):
        if level <= price + epsilon:
            continue
        if excluded_level is not None and abs(level - excluded_level) <= epsilon:
            continue
        candidates.append(level)
    if candidates:
        return min(candidates)

    fallback = [item["high"] for item in _recent_window(candles, config) if item["high"] > price + epsilon]
    if excluded_level is not None:
        fallback = [level for level in fallback if abs(level - excluded_level) > epsilon]
    if fallback:
        return min(fallback)
    return None


def _level_context(price: float, config: dict[str, Any]) -> tuple[float | None, float | None]:
    epsilon = structure_epsilon(config)
    seeds = _seed_levels(config)
    return (
        _nearest_level_below(seeds, price, epsilon),
        _nearest_level_above(seeds, price, epsilon),
    )


def initialize_market_structure(candles: list[dict[str, float]], config: dict[str, Any]) -> dict[str, Any]:
    if not candles:
        base_support, base_resistance = _level_context(0.0, config)
        return {
            "active_support": base_support,
            "active_resistance": base_resistance,
            "support_broken": False,
            "resistance_broken": False,
            "last_break_direction": None,
            "last_flip": None,
            "last_event": None,
            "event_counter": 0,
        }

    price = candles[-1]["close"]
    seed_support, seed_resistance = _level_context(price, config)
    pivot_support = _nearest_pivot_support(candles, price, config)
    pivot_resistance = _nearest_pivot_resistance(candles, price, config)

    active_support = pivot_support or seed_support
    active_resistance = pivot_resistance or seed_resistance

    if active_support is None:
        active_support = seed_support
    if active_resistance is None:
        active_resistance = seed_resistance

    if active_support is not None and active_resistance is not None and active_support >= active_resistance:
        active_support = seed_support
        active_resistance = seed_resistance

    return {
        "active_support": active_support,
        "active_resistance": active_resistance,
        "support_broken": False,
        "resistance_broken": False,
        "last_break_direction": None,
        "last_flip": None,
        "last_event": None,
        "event_counter": 0,
    }


def ensure_market_structure(
    structure: dict[str, Any] | None,
    candles: list[dict[str, float]],
    config: dict[str, Any],
) -> dict[str, Any]:
    if structure is None:
        return initialize_market_structure(candles, config)

    price = candles[-1]["close"] if candles else 0.0
    epsilon = structure_epsilon(config)
    seed_support, seed_resistance = _level_context(price, config)

    if structure.get("active_support") is None:
        structure["active_support"] = _nearest_pivot_support(candles, price, config) or seed_support
    if structure.get("active_resistance") is None:
        structure["active_resistance"] = _nearest_pivot_resistance(candles, price, config) or seed_resistance

    support = structure.get("active_support")
    resistance = structure.get("active_resistance")
    if support is not None and resistance is not None and support >= resistance - epsilon:
        structure["active_support"] = (
            _nearest_pivot_support(candles, price, config, excluded_level=resistance) or seed_support
        )
        structure["active_resistance"] = (
            _nearest_pivot_resistance(candles, price, config, excluded_level=support) or seed_resistance
        )

    return structure


def _build_event(
    structure: dict[str, Any],
    kind: str,
    state: str,
    message: str,
    candle: dict[str, float],
    reference_level: float | None,
) -> dict[str, Any]:
    structure["event_counter"] = int(structure.get("event_counter", 0)) + 1
    event = {
        "kind": kind,
        "state": state,
        "message": message,
        "closed_at": candle.get("datetime"),
        "sequence": structure["event_counter"],
        "reference_level": reference_level,
    }
    structure["last_event"] = event
    return event


def process_candle_close(
    structure: dict[str, Any],
    candles: list[dict[str, float]],
    config: dict[str, Any],
) -> dict[str, Any] | None:
    if len(candles) < 2:
        return None

    ensure_market_structure(structure, candles, config)

    last_candle = candles[-1]
    prev_candle = candles[-2]
    price = last_candle["close"]
    min_body_ratio = float(_logic(config, "min_body_ratio", 0.5))
    min_reclaim = float(_logic(config, "bounce_min_reclaim", 1.0))

    active_support = structure.get("active_support")
    active_resistance = structure.get("active_resistance")

    if active_support is not None and breakout_valid(last_candle, prev_candle, active_support, "down", min_body_ratio):
        broken_support = active_support
        new_support = _nearest_pivot_support(candles, price, config, excluded_level=broken_support)
        structure["active_support"] = new_support
        structure["active_resistance"] = broken_support
        structure["support_broken"] = True
        structure["resistance_broken"] = False
        structure["last_break_direction"] = "down"
        structure["last_flip"] = {
            "from": "support",
            "level": broken_support,
            "to": "resistance",
        }
        support_text = (
            f"Support aktif baru di {new_support:,.3f}."
            if new_support is not None
            else "Support aktif baru belum terbentuk jelas; tunggu swing low berikutnya."
        )
        return _build_event(
            structure,
            kind="support_breakdown",
            state="support_breakdown_confirmed",
            message=(
                f"Support {broken_support:,.3f} sudah ditembus valid pada penutupan candle. "
                f"Level itu sekarang diperlakukan sebagai resistance hasil S/R flip. {support_text}"
            ),
            candle=last_candle,
            reference_level=broken_support,
        )

    if active_resistance is not None and breakout_valid(last_candle, prev_candle, active_resistance, "up", min_body_ratio):
        broken_resistance = active_resistance
        new_resistance = _nearest_pivot_resistance(candles, price, config, excluded_level=broken_resistance)
        structure["active_support"] = broken_resistance
        structure["active_resistance"] = new_resistance
        structure["support_broken"] = False
        structure["resistance_broken"] = True
        structure["last_break_direction"] = "up"
        structure["last_flip"] = {
            "from": "resistance",
            "level": broken_resistance,
            "to": "support",
        }
        resistance_text = (
            f"Resistance aktif baru di {new_resistance:,.3f}."
            if new_resistance is not None
            else "Resistance aktif baru belum terbentuk jelas; tunggu swing high berikutnya."
        )
        return _build_event(
            structure,
            kind="resistance_breakout",
            state="resistance_breakout_confirmed",
            message=(
                f"Resistance {broken_resistance:,.3f} ditembus valid saat candle close. "
                f"Level itu sekarang menjadi support hasil S/R flip. {resistance_text}"
            ),
            candle=last_candle,
            reference_level=broken_resistance,
        )

    if active_support is not None and bounce_confirmed(last_candle, prev_candle, active_support, min_reclaim):
        structure["support_broken"] = False
        return _build_event(
            structure,
            kind="support_bounce",
            state="support_bounce_confirmed",
            message=(
                f"Harga menolak turun di support aktif {active_support:,.3f} dan candle close kembali menguat. "
                "Support masih valid selama penutupan candle berikutnya tidak merusak level ini."
            ),
            candle=last_candle,
            reference_level=active_support,
        )

    if active_resistance is not None and rejection_confirmed(last_candle, active_resistance, "upper"):
        structure["resistance_broken"] = False
        return _build_event(
            structure,
            kind="resistance_rejection",
            state="resistance_rejection_confirmed",
            message=(
                f"Harga menyentuh resistance aktif {active_resistance:,.3f} lalu ditolak saat candle close. "
                "Resistance masih dihormati dan buyer belum punya konfirmasi breakout yang valid."
            ),
            candle=last_candle,
            reference_level=active_resistance,
        )

    structure["last_event"] = None
    return None
