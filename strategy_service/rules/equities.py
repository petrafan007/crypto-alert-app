def decide(f):
    checks = f["checks"]
    if "dip_entry_qualified" in checks and checks["dip_entry_qualified"]:
        return {"enter": True, "setup": "MARKET_STATE_BOTTOM_V1", "reason": "Confirmed bottoming dip setup under composite watchlist regime."}
    if not checks["current_price_above_sma"]:
        return {"enter": False, "setup": None, "reason": "Fresh quote fell below the completed trend average."}
    if checks["rotation_top_two"]:
        return {"enter": True, "setup": "TREND_ROTATION_V1", "reason": "Top-two positive trend and composite watchlist relative momentum."}
    if checks["pullback_qualified"]:
        return {"enter": True, "setup": "TREND_PULLBACK_V1", "reason": "Positive long trend with two-day RSI and lower-band pullback."}
    return {"enter": False, "setup": None, "reason": "No ranked trend, pullback, or confirmed bottoming setup."}
