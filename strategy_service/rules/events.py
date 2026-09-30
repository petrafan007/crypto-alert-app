def decide(f):
    if f["eligible"] and f["fresh_quote"] and f["risk_allowed"]:
        return {"enter": True, "setup": "EVENT_EDGE_V1", "reason": "Fresh Event assessment and fixed paper risk gates passed."}
    return {"enter": False, "setup": "EVENT_EDGE_V1", "reason": "Event eligibility, quote freshness, or saved risk policy blocked entry."}
