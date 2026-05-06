import math
import numpy as np
from log import logger

def calculate_volatility(price_data):
    """Calculate annualized volatility from price data."""
    if not price_data or len(price_data) < 2:
        return 0.0
    try:
        returns = np.diff(np.log(price_data))
        return np.std(returns) * np.sqrt(365 * 24)
    except Exception as e:
        logger.error(f"Error calculating volatility: {e}")
        return 0.0

def calculate_symbol_snapshot(symbol, get_last_7d_prices_func):
    """Compute technical snapshot and trading signal for a symbol."""
    try:
        price_data = get_last_7d_prices_func(symbol)
        if not price_data or len(price_data) < 2:
            return None

        current_price = float(price_data[-1])
        starting_price = float(price_data[0])
        if starting_price <= 0:
            return None

        price_change = ((current_price - starting_price) / starting_price) * 100
        volatility = calculate_volatility(price_data)

        def pct_change(hours):
            if len(price_data) > hours and price_data[-hours - 1] > 0:
                return ((price_data[-1] - price_data[-hours - 1]) / price_data[-hours - 1]) * 100
            return None

        pct_1d = pct_change(24)
        pct_3d = pct_change(72)
        pct_7d = price_change

        window = price_data[-15:] if len(price_data) >= 15 else price_data[:]
        if len(window) < 2:
            rsi = None
        else:
            gains = [max(0, b - a) for a, b in zip(window, window[1:])]
            losses = [max(0, a - b) for a, b in zip(window, window[1:])]
            avg_gain = (sum(gains) / len(gains)) if gains else 0
            avg_loss = (sum(losses) / len(losses)) if losses else 0
            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))

        def ema(series, span):
            if not series: return 0
            if len(series) < span: return sum(series) / len(series)
            k = 2 / (span + 1)
            e = series[0]
            for value in series[1:]:
                e = value * k + e * (1 - k)
            return e

        macd_val = ema(price_data[-200:], 12) - ema(price_data[-200:], 26) if len(price_data) >= 30 else 0
        macd_signal = 'Bullish' if macd_val >= 0 else 'Bearish'

        samples = price_data[-min(len(price_data), 168):]
        sma7 = sum(samples) / len(samples) if samples else current_price
        sma_relation = 'Above' if current_price >= sma7 else 'Below'

        technical_score = 0
        if sma_relation == 'Above': technical_score += 25
        if rsi is not None and 40 <= rsi <= 70: technical_score += 20
        if pct_1d and pct_1d > 0: technical_score += 15
        if pct_3d and pct_3d > 0: technical_score += 15
        if macd_val >= 0: technical_score += 15

        risk_penalty = min(20, int(volatility * 100))
        technical_score = max(0, min(100, technical_score - risk_penalty))

        if technical_score >= 70: signal = 'BUY'
        elif technical_score <= 35: signal = 'SELL'
        else: signal = 'HOLD'

        return {
            "symbol": symbol,
            "current_price": round(current_price, 2),
            "price_change_7d": round(price_change, 2),
            "pct_1d": round(pct_1d, 2) if pct_1d is not None else None,
            "pct_3d": round(pct_3d, 2) if pct_3d is not None else None,
            "pct_7d": round(pct_7d, 2) if pct_7d is not None else None,
            "volatility": volatility,
            "rsi": round(rsi, 1) if rsi is not None else None,
            "macd_signal": macd_signal,
            "macd_value": round(macd_val, 4),
            "sma_relation": sma_relation,
            "technical_score": technical_score,
            "signal": signal,
            "confidence": max(50, min(95, technical_score)),
            "entry_price": round(current_price, 2),
            "stop_loss": round(current_price * (0.95 if signal == 'BUY' else 1.05), 2),
            "take_profit": round(current_price * (1.15 if signal == 'BUY' else 0.85), 2)
        }
    except Exception as e:
        logger.error(f"Error calculating technical snapshot for {symbol}: {e}")
        return None
