from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

import requests
import websocket

from src.config import get_env, load_config
from src.market_reader import build_market_read, breakout_valid
from src.session_engine import (
    get_current_session,
    get_session_label,
    is_market_open,
    minutes_until_session,
    session_transition_message,
)
from src.telegram_bot import (
    send_caution,
    send_liquidity_alert,
    send_market_closed,
    send_market_read,
    send_session_info,
    send_status,
)


runtime: dict[str, Any] = {
    "config": load_config(),
    "candles": [],
    "live_bucket": None,
    "last_sent_state": None,
    "last_tick_price": None,
    "last_session": None,
    "sent_event_keys": set(),
    "last_caution_key": None,
    "asia_range": {
        "date": None,
        "high": None,
        "low": None,
        "locked": False,
        "high_swept": False,
        "low_swept": False,
        "high_breakout_sent": False,
        "low_breakout_sent": False,
    },
    "bootstrapped": False,
    "last_closed_notice_key": None,
}


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def bucket_start(dt: datetime) -> datetime:
    return dt.replace(minute=(dt.minute // 5) * 5, second=0, microsecond=0)


def today_key(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


def fetch_bootstrap_candles() -> list[dict[str, float]]:
    config = runtime["config"]
    api_key = get_env("TWELVE_API_KEY")
    if not api_key:
        raise RuntimeError("TWELVE_API_KEY is missing")

    response = requests.get(
        "https://api.twelvedata.com/time_series",
        params={
            "symbol": config["symbol"],
            "interval": config["timeframe"],
            "outputsize": config["bootstrap_bars"],
            "apikey": api_key,
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if "values" not in payload:
        raise RuntimeError(f"Unexpected TwelveData response: {payload}")

    candles: list[dict[str, float]] = []
    for item in reversed(payload["values"]):
        candles.append(
            {
                "datetime": parse_dt(item["datetime"]),
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
            }
        )
    return candles


def reset_intraday_runtime() -> None:
    runtime["last_sent_state"] = None
    runtime["last_tick_price"] = None
    runtime["last_session"] = None
    runtime["sent_event_keys"] = set()
    runtime["last_caution_key"] = None
    runtime["asia_range"] = {
        "date": None,
        "high": None,
        "low": None,
        "locked": False,
        "high_swept": False,
        "low_swept": False,
        "high_breakout_sent": False,
        "low_breakout_sent": False,
    }


def bootstrap() -> None:
    runtime["config"] = load_config()
    runtime["candles"] = fetch_bootstrap_candles()[-runtime["config"]["logic"]["max_history"]:]
    runtime["live_bucket"] = None
    reset_intraday_runtime()
    runtime["bootstrapped"] = True


def maybe_send_read(price: float) -> None:
    candles = runtime["candles"]
    if len(candles) < 2:
        return

    read_data = build_market_read(
        price=price,
        last_candle=candles[-1],
        prev_candle=candles[-2],
        config=runtime["config"],
    )

    state = read_data["state"]
    if state != runtime["last_sent_state"]:
        runtime["last_sent_state"] = state
        send_market_read(state=state, price=price, message=read_data["message"])
        print(f"STATE -> {state}")


def update_asia_range(price: float, now: datetime, session_name: str | None) -> None:
    asia = runtime["asia_range"]
    current_date = today_key(now)
    if asia["date"] != current_date:
        runtime["asia_range"] = {
            "date": current_date,
            "high": None,
            "low": None,
            "locked": False,
            "high_swept": False,
            "low_swept": False,
            "high_breakout_sent": False,
            "low_breakout_sent": False,
        }
        asia = runtime["asia_range"]

    if session_name == "asia":
        asia["high"] = price if asia["high"] is None else max(asia["high"], price)
        asia["low"] = price if asia["low"] is None else min(asia["low"], price)


def lock_asia_range_if_needed(session_name: str | None) -> None:
    asia = runtime["asia_range"]
    if session_name != "asia" and asia["high"] is not None and asia["low"] is not None and not asia["locked"]:
        asia["locked"] = True
        send_liquidity_alert(
            "ASIA RANGE TERBENTUK",
            (
                f"High Asia: {asia['high']:,.3f}\n"
                f"Low Asia : {asia['low']:,.3f}\n"
                "Level ini akan dipakai sebagai referensi likuiditas untuk sesi berikutnya."
            ),
        )


def maybe_send_session_events(now: datetime, price: float) -> None:
    config = runtime["config"]
    sessions = config["sessions"]
    session_name = get_current_session(now, sessions)
    previous_session = runtime["last_session"]

    update_asia_range(price, now, session_name)
    lock_asia_range_if_needed(session_name)

    if session_name != previous_session:
        runtime["last_session"] = session_name
        if session_name:
            title, body = session_transition_message(session_name, sessions)
            send_session_info(title, body)

    for warning_minute in config.get("session_warnings", {}).get("london_open_minutes", []):
        remaining = minutes_until_session(now, sessions, "london")
        if remaining == warning_minute:
            key = f"{today_key(now)}_london_{warning_minute}"
            if key not in runtime["sent_event_keys"]:
                runtime["sent_event_keys"].add(key)
                send_session_info(
                    "SESSION ALERT",
                    f"{warning_minute} menit lagi sesi London dimulai. Waspadai Judas swing dan sapuan likuiditas sebelum arah market menjadi jelas.",
                )

    for warning_minute in config.get("session_warnings", {}).get("new_york_open_minutes", []):
        remaining = minutes_until_session(now, sessions, "new_york")
        if remaining == warning_minute:
            key = f"{today_key(now)}_newyork_{warning_minute}"
            if key not in runtime["sent_event_keys"]:
                runtime["sent_event_keys"].add(key)
                send_session_info(
                    "SESSION ALERT",
                    f"{warning_minute} menit lagi sesi New York dimulai. Siapkan diri untuk potensi kenaikan volatilitas.",
                )


def maybe_send_asia_liquidity_events(price: float) -> None:
    asia = runtime["asia_range"]
    if not asia["locked"] or asia["high"] is None or asia["low"] is None:
        return

    candles = runtime["candles"]
    if len(candles) < 2:
        return

    config = runtime["config"]
    last_candle = candles[-1]
    prev_candle = candles[-2]
    ratio = config["logic"]["min_body_ratio"]

    if price > asia["high"] and not asia["high_swept"]:
        asia["high_swept"] = True
        send_liquidity_alert(
            "ASIA HIGH DISAPU",
            f"Harga baru saja menyentuh atau melewati high Asia {asia['high']:,.3f}. Tunggu apakah harga lanjut naik atau justru kembali turun.",
        )

    if price < asia["low"] and not asia["low_swept"]:
        asia["low_swept"] = True
        send_liquidity_alert(
            "ASIA LOW DISAPU",
            f"Harga baru saja menyentuh atau melewati low Asia {asia['low']:,.3f}. Tunggu apakah harga lanjut turun atau justru kembali naik.",
        )

    if breakout_valid(last_candle, prev_candle, asia["high"], "up", ratio) and not asia["high_breakout_sent"]:
        asia["high_breakout_sent"] = True
        send_liquidity_alert(
            "BREAKOUT DI ATAS ASIA HIGH",
            f"Harga menembus high Asia {asia['high']:,.3f} dengan penutupan candle yang valid. Perhatikan apakah harga mampu bertahan di atas level ini.",
        )

    if breakout_valid(last_candle, prev_candle, asia["low"], "down", ratio) and not asia["low_breakout_sent"]:
        asia["low_breakout_sent"] = True
        send_liquidity_alert(
            "BREAKOUT DI BAWAH ASIA LOW",
            f"Harga menembus low Asia {asia['low']:,.3f} dengan penutupan candle yang valid. Perhatikan apakah harga mampu bertahan di bawah level ini.",
        )


def build_caution(price: float, now: datetime) -> tuple[str, str] | None:
    config = runtime["config"]
    levels = config["levels"]
    logic = config["logic"]
    session_name = runtime["last_session"]
    lower = levels["lower_decision"]
    upper_supply = levels["upper_supply"]
    upper_breakout = levels["upper_breakout"]
    near_buffer = logic["near_buffer"]

    candles = runtime["candles"]
    if len(candles) < 2:
        return None
    last_candle = candles[-1]
    prev_candle = candles[-2]

    middle_area = (lower + near_buffer) < price < (upper_supply - near_buffer)
    if session_name == "asia" and middle_area:
        return (
            "asia_middle",
            "Sesi Asia cenderung lebih tenang. Selama harga masih berada di area tengah dan belum dekat level penting, belum ada alasan kuat untuk entry.",
        )

    if middle_area:
        return (
            "middle_area",
            "Harga masih berada di area tengah, belum dekat support minor atau resistance minor. Belum ada alasan kuat untuk entry.",
        )

    if price > upper_breakout and not breakout_valid(last_candle, prev_candle, upper_breakout, "up", logic["min_body_ratio"]):
        return (
            "weak_breakout_up",
            f"Harga sempat melewati resistance penting {upper_breakout:,.3f}, tetapi penembusan belum valid. Hindari entry hanya karena spike.",
        )

    if price < lower and not breakout_valid(last_candle, prev_candle, lower, "down", logic["min_body_ratio"]):
        return (
            "weak_breakdown_down",
            f"Harga sempat melewati support minor {lower:,.3f}, tetapi penembusan belum valid. Hindari entry terburu-buru sebelum ada penutupan candle yang jelas.",
        )

    if session_name == "pre_london":
        return (
            "pre_london_caution",
            "Market sedang berada di fase pra-London. Waspadai sapuan likuiditas dan hindari entry terlalu cepat sebelum arah market lebih jelas.",
        )

    return None


def maybe_send_caution(price: float, now: datetime) -> None:
    caution = build_caution(price, now)
    if caution is None:
        runtime["last_caution_key"] = None
        return

    key, message = caution
    if key != runtime["last_caution_key"]:
        runtime["last_caution_key"] = key
        send_caution(message)


def handle_tick(price: float, tick_dt: datetime) -> None:
    current_bucket = bucket_start(tick_dt)
    live_bucket = runtime["live_bucket"]

    maybe_send_session_events(tick_dt, price)

    if live_bucket is None:
        runtime["live_bucket"] = {
            "datetime": current_bucket,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
        }
        maybe_send_read(price)
        maybe_send_asia_liquidity_events(price)
        maybe_send_caution(price, tick_dt)
        return

    if live_bucket["datetime"] == current_bucket:
        live_bucket["high"] = max(live_bucket["high"], price)
        live_bucket["low"] = min(live_bucket["low"], price)
        live_bucket["close"] = price
        maybe_send_read(price)
        maybe_send_asia_liquidity_events(price)
        maybe_send_caution(price, tick_dt)
        return

    closed = live_bucket.copy()
    runtime["candles"].append(closed)
    max_history = runtime["config"]["logic"]["max_history"]
    runtime["candles"] = runtime["candles"][-max_history:]

    runtime["live_bucket"] = {
        "datetime": current_bucket,
        "open": price,
        "high": price,
        "low": price,
        "close": price,
    }
    maybe_send_read(price)
    maybe_send_asia_liquidity_events(price)
    maybe_send_caution(price, tick_dt)


def on_open(ws: websocket.WebSocketApp) -> None:
    config = runtime["config"]
    print("WS connected")
    send_status("Bot live reader aktif. Menunggu market read, session info, dan liquidity alert berikutnya.")
    ws.send(
        json.dumps(
            {
                "action": "subscribe",
                "params": {
                    "symbols": config["symbol"],
                    "type": "price",
                },
            }
        )
    )


def on_message(ws: websocket.WebSocketApp, message: str) -> None:
    try:
        payload = json.loads(message)
        if "price" not in payload:
            return

        now = datetime.now()
        if not is_market_open(now, runtime["config"]["market_hours"]):
            return

        price = float(payload["price"])
        last_price = runtime["last_tick_price"]
        min_tick_change = runtime["config"]["logic"]["min_tick_change"]

        if last_price is not None and abs(price - last_price) < min_tick_change:
            return

        runtime["last_tick_price"] = price
        handle_tick(price, now)
    except Exception as exc:
        print(f"Message error: {exc}")


def on_error(ws: websocket.WebSocketApp, error: Any) -> None:
    print(f"WS error: {error}")


def on_close(ws: websocket.WebSocketApp, status_code: Any, msg: Any) -> None:
    print("WS closed")


def run_ws() -> None:
    api_key = get_env("TWELVE_API_KEY")
    if not api_key:
        raise RuntimeError("TWELVE_API_KEY is missing")

    while True:
        runtime["config"] = load_config()
        now = datetime.now()
        if not is_market_open(now, runtime["config"]["market_hours"]):
            notice_key = now.strftime("%Y-%m-%d-%H")
            if runtime["last_closed_notice_key"] != notice_key:
                runtime["last_closed_notice_key"] = notice_key
                send_market_closed(
                    "Market sedang tutup. Bot standby dan akan mulai membaca market lagi saat jam buka berikutnya tiba."
                )
            runtime["bootstrapped"] = False
            time.sleep(300)
            continue

        runtime["last_closed_notice_key"] = None
        if not runtime["bootstrapped"]:
            bootstrap()
            send_status("Bootstrap candle berhasil dimuat. Bot sedang mulai koneksi websocket.")

        try:
            ws = websocket.WebSocketApp(
                f"wss://ws.twelvedata.com/v1/quotes/price?apikey={api_key}",
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            ws.run_forever()
        except KeyboardInterrupt:
            send_status("Bot dihentikan manual dari terminal.")
            print("Stopped manually")
            break
        except Exception as exc:
            print(f"Reconnect error: {exc}")
            send_status(f"Websocket putus. Reconnect dalam 5 detik. Error: {exc}")
            time.sleep(5)
