def decide(f):
    c = f["checks"]
    ready = c["price_above_entry_channel"] and c["dominance_gate_passed"]
    if ready and c["price_above_trend_sma"] and c["atr_above_noise_floor"]:
        return {"enter": True, "setup": "DONCHIAN_DOMINANCE_V1", "reason": "Completed-hour breakout, trend, volatility and dominance gates passed."}
    return {"enter": False, "setup": "DONCHIAN_DOMINANCE_V1", "reason": "Breakout, trend, volatility or dominance gate did not pass."}
