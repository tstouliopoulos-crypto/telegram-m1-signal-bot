import os
import time
import threading
import requests
from flask import Flask, jsonify

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
API_KEY = os.getenv("OTCHARTS_API_KEY", "")

SYMBOL = "EURUSD_otc"
last_candle = None


def send_message(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram credentials missing")
        return

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text},
            timeout=15
        )
        print("Telegram response:", r.status_code, r.text[:200])
    except Exception as e:
        print("Telegram error:", str(e))


def get_candles():
    if not API_KEY:
        raise RuntimeError("OTCHARTS_API_KEY is missing")

    r = requests.get(
        "https://otcharts.com/v1/candles",
        headers={"Authorization": f"Bearer {API_KEY}"},
        params={
            "venue": "otc",
            "symbol": SYMBOL,
            "tf": 60,
            "limit": 50
        },
        timeout=20
    )

    r.raise_for_status()
    data = r.json()
    candles = data.get("candles", [])

    if not candles:
        raise RuntimeError("API returned no candles")

    return [
        {
            "time": int(x["time"]),
            "open": float(x["open"]),
            "close": float(x["close"])
        }
        for x in candles
    ]


def ema(values, period):
    if len(values) < period:
        return None

    result = values[0]
    k = 2 / (period + 1)

    for value in values[1:]:
        result = value * k + result * (1 - k)

    return result


def analyse(candles):
    # Ignore the currently forming candle.
    closed = candles[:-1]

    if len(closed) < 30:
        return "WAIT", "Not enough candles"

    closes = [c["close"] for c in closed]
    fast = ema(closes[-30:], 9)
    slow = ema(closes[-30:], 21)

    previous = closed[-2]
    last = closed[-1]

    if fast is None or slow is None:
        return "WAIT", "EMA unavailable"

    body = abs(last["close"] - last["open"])
    bodies = [
        abs(c["close"] - c["open"])
        for c in closed[-11:-1]
    ]
    average_body = sum(bodies) / len(bodies) if bodies else 0

    if average_body and body > average_body * 2.5:
        return "WAIT", "Large candle; avoid entry"

    if (
        fast > slow
        and previous["close"] < previous["open"]
        and last["close"] > last["open"]
        and last["close"] > fast
    ):
        return "UP", "Bullish EMA and candle confirmation"

    if (
        fast < slow
        and previous["close"] > previous["open"]
        and last["close"] < last["open"]
        and last["close"] < fast
    ):
        return "DOWN", "Bearish EMA and candle confirmation"

    return "WAIT", "No clear confirmation"


def loop():
    global last_candle

    while True:
        try:
            candles = get_candles()

            if len(candles) < 3:
                raise RuntimeError("Not enough candle data")

            closed_time = candles[-2]["time"]

            if closed_time != last_candle:
                last_candle = closed_time
                signal, reason = analyse(candles)

                if signal in ("UP", "DOWN"):
                    message = (
                        f"{'🟢' if signal == 'UP' else '🔴'} "
                        f"{signal}\n"
                        f"EUR/USD OTC\n"
                        f"Timeframe: M1\n"
                        f"Reason: {reason}\n"
                        f"Signal only — DEMO first"
                    )
                    send_message(message)
                    print(message)
                else:
                    print("WAIT:", reason)

        except Exception as e:
            print("BOT ERROR:", str(e))

        # One API request per minute; check your API quota.
        time.sleep(60)


@app.get("/")
def home():
    return jsonify({
        "status": "online",
        "service": "Telegram M1 Signal Bot",
        "symbol": SYMBOL,
        "mode": "signal-only"
    })


@app.get("/health")
def health():
    return "OK", 200


if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "10000"))
    )
