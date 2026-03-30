from __future__ import annotations

from datetime import datetime

import src.ws_client as wc
from src.market_reader_live_fixed import build_market_read, breakout_valid


WATCH_STATES = {"near_lower_range", "upper_supply_zone", "upper_breakout_watch"}


wc.runtime.setdefault("intrabar_watch_state", None)
wc.runtime.setdefault("intrabar_watch_sent_at", None)
wc.runtime.setdefault(
    "structure_state",
    {"lower_decision_flipped": False, "upper_breakout_flipped": False},
)


_original_reset = wc.reset_intraday_runtime


def reset_intraday_runtime() -> None:
    _original_reset()
    wc.runtime["intrabar_watch_state"] = None
    wc.runtime["intrabar_watch_sent_at"] = None
    wc.runtime["structure_state"] = {
        "lower_decision_flipped": False,
        "upper_breakout_flipped": False,
    }


def state_hysteresis() -> float:
    logic = wc.runtime["config"]["logic"]
    return float(logic.get("state_hysteresis", max(logic["near_buffer"] * 0.2, 2.0)))


def maybe_clear_intrabar_watch(price: float) -> None:
    active = wc.runtime.get("intrabar_watch_state")
    if active is None:
        return

    levels = wc.runtime["config"]["levels"]
    hysteresis = state_hysteresis()

    if active == "near_lower_range":
        if price >= levels["tp_mid"] + hysteresis:
            wc.runtime["intrabar_watch_state"] = None
        return

    if active == "upper_supply_zone":
        if price <= levels["upper_supply"] - hysteresis or price >= levels["upper_breakout"] + hysteresis:
            wc.runtime["intrabar_watch_state"] = None
        return

    if active == "upper_breakout_watch":
        if price <= levels["upper_supply"] - hysteresis or price >= levels["upper_extreme"] + hysteresis:
            wc.runtime["intrabar_watch_state"] = None
        return


def update_structure_state() -> None:
    candles = wc.runtime["candles"]
    if len(candles) < 2:
        return

    config = wc.runtime["config"]
    levels = config["levels"]
    logic = config["logic"]
    structure_state = wc.runtime["structure_state"]

    last_candle = candles[-1]
    prev_candle = candles[-2]

    lower_decision = levels["lower_decision"]
    upper_breakout = levels["upper_breakout"]

    if breakout_valid(last_candle, prev_candle, lower_decision, "down", logic["min_body_ratio"]):
        structure_state["lower_decision_flipped"] = True

    if breakout_valid(last_candle, prev_candle, lower_decision, "up", logic["min_body_ratio"]):
        structure_state["lower_decision_flipped"] = False

    if breakout_valid(last_candle, prev_candle, upper_breakout, "up", logic["min_body_ratio"]):
        structure_state["upper_breakout_flipped"] = True

    if breakout_valid(last_candle, prev_candle, upper_breakout, "down", logic["min_body_ratio"]):
        structure_state["upper_breakout_flipped"] = False


def maybe_send_read(price: float, now: datetime | None = None, intrabar: bool = False) -> None:
    candles = wc.runtime["candles"]
    if len(candles) < 2:
        return

    read_data = build_market_read(
        price=price,
        last_candle=candles[-1],
        prev_candle=candles[-2],
        config=wc.runtime["config"],
        structure_state=wc.runtime["structure_state"],
    )

    state = read_data["state"]

    if intrabar:
        if state not in WATCH_STATES:
            return
        if state == wc.runtime.get("intrabar_watch_state"):
            return

        cooldown = int(wc.runtime["config"]["logic"].get("intrabar_watch_cooldown_seconds", 180))
        last_sent_at = wc.runtime.get("intrabar_watch_sent_at")
        if now is not None and last_sent_at is not None:
            if (now - last_sent_at).total_seconds() < cooldown:
                return

        wc.runtime["intrabar_watch_state"] = state
        wc.runtime["intrabar_watch_sent_at"] = now
        wc.runtime["last_sent_state"] = state
        wc.send_market_read(state=state, price=price, message=read_data["message"])
        print(f"INTRABAR WATCH -> {state}")
        return

    if state in WATCH_STATES:
        wc.runtime["intrabar_watch_state"] = state
    else:
        wc.runtime["intrabar_watch_state"] = None

    if state != wc.runtime["last_sent_state"]:
        wc.runtime["last_sent_state"] = state
        wc.send_market_read(state=state, price=price, message=read_data["message"])
        print(f"STATE -> {state}")


def handle_tick(price: float, tick_dt: datetime) -> None:
    current_bucket = wc.bucket_start(tick_dt)
    live_bucket = wc.runtime["live_bucket"]

    wc.maybe_send_session_events(tick_dt, price)
    wc.maybe_send_news_events(tick_dt)

    if live_bucket is None:
        wc.runtime["live_bucket"] = {
            "datetime": current_bucket,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
        }
        maybe_clear_intrabar_watch(price)
        maybe_send_read(price, now=tick_dt, intrabar=True)
        wc.maybe_send_asia_liquidity_events(price)
        wc.maybe_send_caution(price, tick_dt)
        return

    if live_bucket["datetime"] == current_bucket:
        live_bucket["high"] = max(live_bucket["high"], price)
        live_bucket["low"] = min(live_bucket["low"], price)
        live_bucket["close"] = price
        maybe_clear_intrabar_watch(price)
        maybe_send_read(price, now=tick_dt, intrabar=True)
        wc.maybe_send_asia_liquidity_events(price)
        wc.maybe_send_caution(price, tick_dt)
        return

    closed = live_bucket.copy()
    wc.runtime["candles"].append(closed)
    max_history = wc.runtime["config"]["logic"]["max_history"]
    wc.runtime["candles"] = wc.runtime["candles"][-max_history:]

    update_structure_state()
    maybe_send_read(closed["close"], intrabar=False)

    wc.runtime["live_bucket"] = {
        "datetime": current_bucket,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
    }
    maybe_clear_intrabar_watch(price)
    maybe_send_read(price, now=tick_dt, intrabar=True)
    wc.maybe_send_asia_liquidity_events(price)
    wc.maybe_send_caution(price, tick_dt)


wc.reset_intraday_runtime = reset_intraday_runtime
wc.maybe_send_read = maybe_send_read
wc.handle_tick = handle_tick


if __name__ == "__main__":
    wc.run_ws()
