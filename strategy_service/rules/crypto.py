def decide(f):
    c = f["checks"]
    ready = c["price_above_entry_channel"] and c["dominance_gate_passed"]
    if ready:
        return {"enter": True, "setup": "DONCHIAN_DOMINANCE_V1", "reason": "Completed-hour breakout and dominance gates passed."}
    return {"enter": False, "setup": "DONCHIAN_DOMINANCE_V1", "reason": "Breakout or dominance gate did not pass."}
