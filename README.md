# Telegram M1 Signal Bot

Ready for Render deployment.

1. Upload these files to a GitHub repository.
2. In Render choose New -> Web Service.
3. Connect the repository.
4. Build: `pip install -r requirements.txt`
5. Start: `gunicorn app:app`
6. Add environment variables `BOT_TOKEN` and `CHAT_ID`.

Signal-only: no trades are executed. Never publish the Telegram token in GitHub.

Signals use public Binance 1-minute candles, not Pocket Option OTC.

Render free web services spin down after 15 minutes without inbound traffic, so free hosting is not reliable for 24/7 signals. Continuous operation needs an always-on service/worker.
