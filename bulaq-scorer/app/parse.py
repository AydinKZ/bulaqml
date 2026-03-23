def extract_value(payload: dict):
    if payload.get("value_float") is not None:
        return payload["value_float"], "numeric"
    if payload.get("value_int") is not None:
        return payload["value_int"], "numeric"
    if payload.get("value_bool") is not None:
        return payload["value_bool"], "bool"
    if payload.get("value_str") is not None:
        return payload["value_str"], "cat"
    if "value" in payload:
        v = payload["value"]

        if isinstance(v, bool):
            return v, "bool"

        if isinstance(v, (int, float)):
            return v, "numeric"

        if isinstance(v, str):
            return v, "cat"

    return None, None