def decide(f):
    c = f["checks"]
    direction = c["direction"]
    if direction == None:
        return {"enter": False, "setup": f["basis"], "reason": "Underlying trend does not support an out-of-money credit spread."}
    if c["annual_iv_rank_252"] != None:
        ready = c["annual_iv_rank_252"] >= f["min_ivr"]
    elif c["short_iv_percentile_30"] != None:
        ready = c["short_iv_percentile_30"] >= f["min_ivr"]
    else:
        ready = c["current_atm_iv"] >= 1.05 * c["rv_20"]
    if ready:
        return {"enter": True, "setup": f["basis"], "reason": "Directional trend and labeled volatility regime qualify."}
    return {"enter": False, "setup": f["basis"], "reason": "Volatility regime is below the saved entry threshold."}
