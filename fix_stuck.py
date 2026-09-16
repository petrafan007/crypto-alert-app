import sys
import os
from app import create_app, db
from models import WatchlistCoin

app = create_app()
with app.app_context():
    coins = WatchlistCoin.query.filter_by(sentiment="Checking now...").all()
    count = 0
    for coin in coins:
        coin.sentiment = "Error"
        coin.sentiment_reason = "Cleared stuck state manually"
        count += 1
    db.session.commit()
    print(f"Cleared {count} stuck coins.")
