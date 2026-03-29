from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

import requests
import websocket

from src.config import get_env, load_config
from src.market_reader import build_market_read
from src.telegram_bot import send_market_read, send_status


runtime: dict[str, Any] = {
    "config": load_config(),
    "candles": [],
    "live_bucket": None,
    "last_sent_state": None,
    "last_tick_price": None,
}


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def bucket_start(dt: datetime) -> datetime:
    return dt.replace(minute=(dt.minute // 5) * 5, second=0, microsecond=0)


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


def bootstrap() -> None:
    runtime["config"] = load_config()
    runtime["candles"] = fetch_bootstrap_candles()[-runtime["config"]["logic"]["max_history"]:]
    runtime["live_bucket"] = None
    runtime["last_sent_state"] = None


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


def handle_tick(price: float, tick_dt: datetime) -> None:
    current_bucket = bucket_start(tick_dt)
    live_bucket = runtime["live_bucket"]

    if live_bucket is None:
        runtime["live_bucket"] = {
            "datetime": current_bucket,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
        }
        maybe_send_read(price)
        return

    if live_bucket["datetime"] == current_bucket:
        live_bucket["high"] = max(live_bucket["high"], price)
        live_bucket["low"] = min(live_bucket["low"], price)
        live_bucket["close"] = price
        maybe_send_read(price)
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


def on_open(ws: websocket.WebSocketApp) -> None:
    config = runtime["config"]
    print("WS connected")
    send_status("Bot live reader aktif. Menunggu market read berikutnya.")
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

        price = float(payload["price"])
        last_price = runtime["last_tick_price"]
        min_tick_change = runtime["config"]["logic"]["min_tick_change"]

        if last_price is not None and abs(price - last_price) < min_tick_change:
            return

        runtime["last_tick_price"] = price
        handle_tick(price, datetime.now())
    except Exception as exc:
        print(f"Message error: {exc}")


def on_error(ws: websocket.WebSocketApp, error: Any) -> None:
    print(f"WS error: {error}")


def on_close(ws: websocket.WebSocketApp, status_code: Any, msg: Any) -> None:
    print("WS closed")


def run_ws() -> None:
    bootstrap()
    api_key = get_env("TWELVE_API_KEY")
    if not api_key:
        raise RuntimeError("TWELVE_API_KEY is missing")

    send_status("Bootstrap candle berhasil dimuat. Bot sedang mulai koneksi websocket.")

    while True:
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
