def decide(f):
    c = f["checks"]
    ready = c["price_above_entry_channel"] and c["dominance_gate_passed"]
    if ready and c["price_above_trend_sma"] and c["atr_above_noise_floor"]:
        if "market_state" in c and (c["market_state"] == "still_falling" or c["market_state"] == "topping"):
            return {"enter": False, "setup": "DONCHIAN_DOMINANCE_V1", "reason": "Market-state classifier blocked falling-knife or topping entry."}
        return {"enter": True, "setup": "DONCHIAN_DOMINANCE_V1", "reason": "Completed-hour breakout, trend, volatility and dominance gates passed."}
    if "dip_entry_qualified" in c and c["dip_entry_qualified"] and c["dominance_gate_passed"] and c["atr_above_noise_floor"]:
        return {"enter": True, "setup": "CRYPTO_BOTTOM_DIP_V1", "reason": "Confirmed bottoming dip setup passed volatility and dominance gates."}
    return {"enter": False, "setup": "DONCHIAN_DOMINANCE_V1", "reason": "Breakout, bottoming dip, trend, volatility or dominance gate did not pass."}
