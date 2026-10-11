import os
import time
import threading
import logging
import requests
from flask import Flask, jsonify

# Telegram M1 signal bot — signals only; it does not place trades.
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("signal-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "").strip()  # Optional; /start can register the chat.
API_KEY = os.getenv("OTCHARTS_API_KEY", "").strip()
SYMBOL = os.getenv("SYMBOL", "EURUSD_otc").strip()
POLL_SECONDS = 60
TELEGRAM_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

last_candle_time = None
registered_chat_ids = set()
state_lock = threading.Lock()


def telegram_call(method, payload=None, timeout=20):
    if not BOT_TOKEN:
        log.error("BOT_TOKEN is missing in Render Environment.")
        return None
    try:
        response = requests.post(
            f"{TELEGRAM_BASE}/{method}",
            json=payload or {},
            timeout=timeout,
        )
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            log.error("Telegram API error for %s: %s", method, result)
            return None
        return result.get("result")
    except Exception:
        log.exception("Telegram request failed (%s)", method)
        return None


def send_message(text, chat_id=None):
    targets = []
    if chat_id is not None:
        targets = [str(chat_id)]
    else:
        if CHAT_ID:
            targets.append(CHAT_ID)
        with state_lock:
            targets.extend(str(x) for x in registered_chat_ids if str(x) not in targets)

    if not targets:
        log.warning("No Telegram chat registered yet. Open the bot and send /start.")
        return

    for target in targets:
        telegram_call("sendMessage", {
            "chat_id": target,
            "text": text,
            "disable_web_page_preview": True,
        })


def get_candles():
    if not API_KEY:
        log.error("OTCHARTS_API_KEY is missing in Render Environment.")
        return []

    response = requests.get(
        "https://otcharts.com/v1/candles",
        headers={"Authorization": f"Bearer {API_KEY}"},
        params={
            "venue": "otc",
            "symbol": SYMBOL,
            "tf": 60,
            "limit": 50,
        },
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    candles = data.get("candles", []) if isinstance(data, dict) else []

    cleaned = []
    for candle in candles:
        try:
            cleaned.append({
                "time": int(candle["time"]),
                "open": float(candle["open"]),
                "close": float(candle["close"]),
                "high": float(candle.get("high", max(float(candle["open"]), float(candle["close"])))),
                "low": float(candle.get("low", min(float(candle["open"]), float(candle["close"])))),
            })
        except (KeyError, TypeError, ValueError):
            continue
    cleaned.sort(key=lambda item: item["time"])
    return cleaned


def ema(values, period):
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def analyze(candles):
    # Use closed candles only: the newest candle may still be forming.
    closed = candles[:-1]
    if len(closed) < 25:
        return "ΠΕΡΙΜΕΝΕΤΕ", "Δεν υπάρχουν αρκετά κλεισμένα κεριά για έλεγχο."

    closes = [c["close"] for c in closed]
    fast = ema(closes[-30:], 9)
    slow = ema(closes[-30:], 21)
    if fast is None or slow is None:
        return "ΠΕΡΙΜΕΝΕΤΕ", "Δεν υπάρχουν αρκετά δεδομένα για EMA 9/21."

    previous_fast = ema(closes[-31:-1], 9) if len(closes) >= 31 else None
    previous_slow = ema(closes[-31:-1], 21) if len(closes) >= 31 else None
    last = closed[-1]
    previous = closed[-2]
    bullish = last["close"] > last["open"]
    bearish = last["close"] < last["open"]

    # Conservative signal: EMA direction and last two candle directions agree.
    if fast > slow and bullish and previous["close"] > previous["open"]:
        return "ΕΠΑΝΩ", "EMA 9 πάνω από EMA 21 και δύο ανοδικά κλεισμένα κεριά."
    if fast < slow and bearish and previous["close"] < previous["open"]:
        return "ΚΑΤΩ", "EMA 9 κάτω από EMA 21 και δύο πτωτικά κλεισμένα κεριά."

    # Explicitly avoid a signal when EMAs are crossing or candles disagree.
    if previous_fast is not None and previous_slow is not None:
        if (previous_fast <= previous_slow and fast > slow) or (previous_fast >= previous_slow and fast < slow):
            return "ΠΕΡΙΜΕΝΕΤΕ", "Πιθανή αλλαγή τάσης· περιμένουμε επιβεβαίωση."
    return "ΠΕΡΙΜΕΝΕΤΕ", "Δεν υπάρχει αρκετή επιβεβαίωση από τα κεριά και τους EMA."


def telegram_listener():
    if not BOT_TOKEN:
        log.error("Telegram listener not started: BOT_TOKEN is missing.")
        return

    # Long polling and an active webhook cannot be used at the same time.
    telegram_call("deleteWebhook", {"drop_pending_updates": False})
    offset = None
    log.info("Telegram listener started.")
    while True:
        try:
            params = {"timeout": 25}
            if offset is not None:
                params["offset"] = offset
            response = requests.get(
                f"{TELEGRAM_BASE}/getUpdates",
                params=params,
                timeout=35,
            )
            response.raise_for_status()
            body = response.json()
            if not body.get("ok"):
                log.error("getUpdates returned an error: %s", body)
                time.sleep(5)
                continue

            for update in body.get("result", []):
                offset = update["update_id"] + 1
                message = update.get("message") or update.get("edited_message")
                if not message:
                    continue
                chat = message.get("chat", {})
                chat_id = chat.get("id")
                text = (message.get("text") or "").strip()
                if not chat_id:
                    continue

                if text.startswith("/start") or text.startswith("/help"):
                    with state_lock:
                        registered_chat_ids.add(str(chat_id))
                    send_message(
                        "Γεια σου! Το bot EUR/USD OTC είναι ενεργό.\n\n"
                        "Στέλνω μόνο ενδεικτικά σήματα, δεν εκτελώ συναλλαγές.\n"
                        "Έλεγχος κεριών: περίπου κάθε 60 δευτερόλεπτα.\n\n"
                        "Εντολές:\n"
                        "/start — ενεργοποίηση μηνυμάτων\n"
                        "/signal — έλεγχος για το πιο πρόσφατο σήμα\n"
                        "/status — κατάσταση bot",
                        chat_id=chat_id,
                    )
                elif text.startswith("/status"):
                    send_message(
                        f"Bot online.\nΣύμβολο: {SYMBOL}\n"
                        f"OTCharts API key: {'ρυθμισμένο' if API_KEY else 'λείπει'}",
                        chat_id=chat_id,
                    )
                elif text.startswith("/signal"):
                    try:
                        candles = get_candles()
                        signal, reason = analyze(candles)
                        send_message(
                            f"EUR/USD OTC — {signal}\nΑιτία: {reason}\n"
                            "Ενδεικτική ανάλυση, όχι εγγυημένη πρόβλεψη.",
                            chat_id=chat_id,
                        )
                    except Exception:
                        log.exception("Manual /signal check failed")
                        send_message(
                            "Δεν μπόρεσα να διαβάσω τα κεριά από το OTCharts. "
                            "Έλεγξε τα logs του Render και το API key.",
                            chat_id=chat_id,
                        )
                else:
                    send_message("Γράψε /start, /signal ή /status.", chat_id=chat_id)
        except Exception:
            log.exception("Telegram listener error")
            time.sleep(5)


def signal_loop():
    global last_candle_time
    log.info("Signal loop started for %s", SYMBOL)
    while True:
        try:
            candles = get_candles()
            if len(candles) >= 3:
                # Treat the candle before the newest (possibly still forming) candle as closed.
                closed_candle_time = candles[-2]["time"]
                if closed_candle_time != last_candle_time:
                    last_candle_time = closed_candle_time
                    signal, reason = analyze(candles)
                    log.info("Signal: %s — %s", signal, reason)
                    if signal in ("ΕΠΑΝΩ", "ΚΑΤΩ"):
                        send_message(
                            f"📊 EUR/USD OTC — {signal}\n"
                            f"Χρονικό πλαίσιο: M1\n"
                            f"Αιτία: {reason}\n"
                            "⚠️ Ενδεικτικό σήμα, όχι εγγυημένη πρόβλεψη. "
                            "Επιβεβαίωσε το γράφημα πριν από οποιαδήποτε απόφαση."
                        )
            else:
                log.warning("OTCharts returned too few candles.")
        except Exception:
            log.exception("Signal loop failed")
        time.sleep(POLL_SECONDS)


@app.get("/")
def home():
    return jsonify({
        "status": "online",
        "service": "Telegram M1 Signal Bot",
        "mode": "signal-only",
        "symbol": SYMBOL,
    })


@app.get("/health")
def health():
    return "OK", 200


@app.get("/υγεία")
def health_greek():
    return "OK", 200


# Start background workers when the module is imported by Gunicorn on Render.
# Render normally runs this app with a WSGI server, so these must not be
# started only inside the __main__ block.
_workers_started = False
_workers_lock = threading.Lock()


def start_background_workers():
    global _workers_started
    with _workers_lock:
        if _workers_started:
            return
        threading.Thread(target=telegram_listener, daemon=True, name="telegram-listener").start()
        threading.Thread(target=signal_loop, daemon=True, name="signal-loop").start()
        _workers_started = True


start_background_workers()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
