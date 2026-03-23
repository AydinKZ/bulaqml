import os
import requests

BASE = os.getenv("SCORER_BASE_URL", "http://localhost:8080")


def api_get(path, **kwargs):
    r = requests.get(f"{BASE}{path}", timeout=12, **kwargs)
    r.raise_for_status()
    return r.json()


def api_post(path, payload):
    r = requests.post(f"{BASE}{path}", json=payload, timeout=12)
    r.raise_for_status()
    return r.json()


def safe_get(path, **kwargs):
    try:
        return api_get(path, **kwargs)
    except Exception:
        return None


def safe_post(path, payload):
    try:
        return api_post(path, payload)
    except Exception as e:
        return {"ok": False, "error": repr(e)}