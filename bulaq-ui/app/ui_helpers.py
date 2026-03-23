import json
from datetime import UTC, datetime

import pandas as pd


def fmt_dt_us(ts_us):
    try:
        return datetime.fromtimestamp(int(ts_us) / 1_000_000, UTC).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "-"


def compact_json(v):
    try:
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(v)

def cfg_default(cfg: dict, *path, fallback=None):
    cur = cfg
    for p in path:
        if not isinstance(cur, dict):
            return fallback
        cur = cur.get(p)
        if cur is None:
            return fallback
    return cur

def status_badge(status: str) -> str:
    if status == "active":
        return "🟢 active"
    if status == "assigned":
        return "🟡 assigned"
    if status == "discovered":
        return "⚪ discovered"
    if status == "disabled":
        return "🔴 disabled"
    return str(status or "-")


def default_model_for_vtype(vtype: str) -> str:
    if vtype == "numeric":
        return "half_space_trees"
    if vtype == "bool":
        return "bernoulli_surprisal"
    if vtype == "cat":
        return "categorical_surprisal"
    return ""


def allowed_models_for_vtype(vtype: str):
    if vtype == "numeric":
        return ["half_space_trees", "ewma_residual"]
    if vtype == "bool":
        return ["bernoulli_surprisal"]
    if vtype == "cat":
        return ["categorical_surprisal"]
    return []


def parse_float(raw, field_name):
    try:
        return float(str(raw).strip())
    except Exception:
        raise ValueError(f"Invalid float for {field_name}: {raw}")


def make_assignment_payload(vtype: str, model_name: str, form_values: dict):
    if vtype == "numeric":
        if model_name == "half_space_trees":
            params = {
                "n_trees": int(form_values["n_trees"]),
                "height": int(form_values["height"]),
                "window_size": int(form_values["window_size"]),
                "threshold_q": float(form_values["threshold_q"]),
                "warmup_min": int(form_values["warmup_min"]),
            }
        elif model_name == "ewma_residual":
            params = {
                "alpha": float(form_values["alpha"]),
                "residual_threshold_q": float(form_values["residual_threshold_q"]),
                "warmup_min": int(form_values["warmup_min"]),
                "min_scale": float(form_values["min_scale"]),
            }
        else:
            raise ValueError(f"Unsupported numeric model: {model_name}")

    elif vtype == "bool":
        params = {
            "bool_threshold_q": float(form_values["bool_threshold_q"]),
            "bool_alpha": float(form_values["bool_alpha"]),
            "bool_flip_rate_hi": float(form_values["bool_flip_rate_hi"]),
            "bool_stuck_sec": int(form_values["bool_stuck_sec"]),
        }

    elif vtype == "cat":
        params = {
            "cat_threshold_q": float(form_values["cat_threshold_q"]),
            "cat_decay": float(form_values["cat_decay"]),
            "cat_smoothing_alpha": float(form_values["cat_smoothing_alpha"]),
            "cat_transition_enable": bool(form_values["cat_transition_enable"]),
            "cat_transition_weight": float(form_values["cat_transition_weight"]),
            "cat_novelty_min_prob": float(form_values["cat_novelty_min_prob"]),
            "cat_new_category_is_anom": bool(form_values["cat_new_category_is_anom"]),
        }

    else:
        raise ValueError(f"Unsupported vtype: {vtype}")

    return {
        "assigned_model": model_name,
        "model_settings_json": {
            "model_family": vtype,
            "model_name": model_name,
            "params": params,
        },
        "actor": "ui",
        "source": "ui",
    }


def extract_existing_params(tag_item: dict):
    msj = (tag_item or {}).get("model_settings_json") or {}
    return dict(msj.get("params") or {})


def make_tags_dataframe(tag_items):
    if not tag_items:
        return pd.DataFrame()

    tags_df = pd.DataFrame(tag_items).copy()

    if "last_seen_ts" in tags_df.columns:
        tags_df["last_seen_text"] = pd.to_datetime(tags_df["last_seen_ts"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        tags_df["last_seen_text"] = "-"

    tags_df["enabled_text"] = (
        tags_df["enabled_for_scoring"].apply(lambda x: "yes" if bool(x) else "no")
        if "enabled_for_scoring" in tags_df.columns
        else "-"
    )
    tags_df["runtime_text"] = (
        tags_df["runtime_loaded"].apply(lambda x: "yes" if bool(x) else "no")
        if "runtime_loaded" in tags_df.columns
        else "-"
    )

    tags_df = tags_df.reset_index(drop=True)
    tags_df.index = tags_df.index + 1
    tags_df.index.name = "#"
    return tags_df