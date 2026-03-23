# scorer.py
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from river import anomaly, stats as river_stats
from typing import Optional, Dict, Any


# -------------------------
# Numeric
# -------------------------
@dataclass
class HSTNumericState:
    model: Any
    q: Any
    last_value: Optional[float] = None


@dataclass
class EWMANumericState:
    mean: Any
    resid_var: Any
    q: Any
    n_seen: int = 0
    last_value: Optional[float] = None
    last_pred: Optional[float] = None
    last_residual: Optional[float] = None


def _make_ewmean(alpha: float):
    EWMean = getattr(river_stats, "EWMean", None)
    if EWMean is None:
        return river_stats.Mean()

    try:
        return EWMean(alpha=alpha)
    except TypeError:
        try:
            return EWMean(fading_factor=alpha)
        except TypeError:
            return river_stats.Mean()


def make_hst_state_from_params(params):
    n_trees = int(params.get("n_trees", 15))
    height = int(params.get("height", 12))
    window_size = int(params.get("window_size", 200))
    threshold_q = float(params.get("threshold_q", 0.995))

    model = anomaly.HalfSpaceTrees(
        n_trees=n_trees,
        height=height,
        window_size=window_size,
        seed=42,
    )
    q = river_stats.Quantile(threshold_q)
    return HSTNumericState(model=model, q=q)


def make_ewma_state_from_params(params):
    alpha = float(params.get("alpha", 0.05))
    residual_threshold_q = float(params.get("residual_threshold_q", 0.995))

    mean = _make_ewmean(alpha)
    resid_var = river_stats.Var()
    q = river_stats.Quantile(residual_threshold_q)

    return EWMANumericState(mean=mean, resid_var=resid_var, q=q)


def score_numeric_hst(state: HSTNumericState, value, params):
    x = float(value)
    feats = {"value": x}
    score = state.model.score_one(feats)
    state.model.learn_one(feats)
    state.q.update(score)
    thr = state.q.get()
    state.last_value = x
    return score, thr, score > thr, "half_space_trees", "score_gt_threshold"


def score_numeric_ewma(state: EWMANumericState, value, params):
    x = float(value)

    warmup_min = int(params.get("warmup_min", 30))
    min_scale = float(params.get("min_scale", 1e-6))

    pred = float(state.mean.get())
    if state.n_seen == 0:
        pred = x

    residual = x - pred

    var_now = float(state.resid_var.get() or 0.0)
    scale = max(math.sqrt(var_now) if var_now > 0 else 0.0, min_scale)
    score = abs(residual) / scale

    state.mean.update(x)
    state.resid_var.update(residual)
    state.q.update(score)
    state.n_seen += 1

    thr = state.q.get()
    is_anom = (state.n_seen >= warmup_min) and (score > thr)

    state.last_value = x
    state.last_pred = pred
    state.last_residual = residual

    return score, thr, is_anom, "ewma_residual", "residual_gt_threshold"


def score_numeric(state, value, params, model_name: str):
    if model_name == "half_space_trees":
        return score_numeric_hst(state, value, params)
    if model_name == "ewma_residual":
        return score_numeric_ewma(state, value, params)
    raise ValueError(f"unsupported numeric model: {model_name}")

# -------------------------
# Bool
# -------------------------
@dataclass
class BoolState:
    p_true: any
    q: any
    toggle_rate: any
    last_value: Optional[bool] = None
    last_change_ts: Optional[float] = None

def _make_ewmean(alpha: float):
    EWMean = getattr(river_stats, "EWMean", None)
    if EWMean is None:
        return river_stats.Mean()

    try:
        return EWMean(alpha=alpha)
    except TypeError:
        try:
            return EWMean(fading_factor=alpha)
        except TypeError:
            return river_stats.Mean()

def make_bool_state(cfg):
    p_true = _make_ewmean(cfg.bool_alpha)
    toggle_rate = _make_ewmean(cfg.bool_alpha)

    q = river_stats.Quantile(
        cfg.bool_threshold_q if hasattr(cfg, "bool_threshold_q") else cfg.threshold_q
    )
    return BoolState(p_true=p_true, q=q, toggle_rate=toggle_rate)

def _clamp_prob(p: float, eps: float) -> float:
    return max(eps, min(1.0 - eps, p))

def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "t", "yes", "y", "on"):
            return True
        if v in ("false", "0", "f", "no", "n", "off"):
            return False
    raise ValueError(f"bool parse failed: {value!r}")


def score_bool(state: BoolState, value, cfg, now_ts: Optional[float] = None):
    x = _parse_bool(value)
    now = float(now_ts if now_ts is not None else time.time())

    # score before update
    p = float(state.p_true.get())
    p = _clamp_prob(p, getattr(cfg, "prob_eps", 1e-9))
    score = -math.log(p) if x else -math.log(1.0 - p)

    # toggle tracking
    toggled = 0.0
    if state.last_value is None:
        state.last_change_ts = now
    else:
        if x != state.last_value:
            toggled = 1.0
            state.last_change_ts = now
    state.last_value = x

    # learn
    state.p_true.update(1.0 if x else 0.0)
    state.toggle_rate.update(toggled)

    # quantile threshold
    state.q.update(score)
    thr = state.q.get()
    is_anom = score > thr
    reason = "score_gt_threshold"

    # chatter rule (maps to your bool_flip_rate_hi)
    flip_hi = getattr(cfg, "bool_flip_rate_hi", 0.2)
    if float(state.toggle_rate.get()) > flip_hi:
        is_anom = True
        reason = "bool_chatter"

    # stuck rule (optional; 0 disables)
    stuck_sec = getattr(cfg, "bool_stuck_sec", 0)
    if stuck_sec and state.last_change_ts is not None and (now - state.last_change_ts) > stuck_sec:
        is_anom = True
        reason = "bool_stuck"

    return score, thr, is_anom, "bernoulli_surprisal", reason


# -------------------------
# Cat
# -------------------------
@dataclass
class CatState:
    counts: Dict[str, float] = field(default_factory=dict)
    total: float = 0.0
    q: any = None
    prev: Optional[str] = None
    trans: Dict[str, Dict[str, float]] = field(default_factory=lambda: defaultdict(dict))
    trans_total: Dict[str, float] = field(default_factory=lambda: defaultdict(float))

def make_cat_state(cfg):
    q = river_stats.Quantile(cfg.cat_threshold_q if hasattr(cfg, "cat_threshold_q") else cfg.threshold_q)
    return CatState(q=q)

def _apply_decay(state: CatState, decay: float):
    # decay ~ 0.999 per event; 1.0 disables
    if decay >= 1.0:
        return
    for k in list(state.counts.keys()):
        state.counts[k] *= decay
        if state.counts[k] < 1e-12:
            del state.counts[k]
    state.total *= decay

    # decay transitions too (if used)
    for prev, m in list(state.trans.items()):
        for cur in list(m.keys()):
            m[cur] *= decay
            if m[cur] < 1e-12:
                del m[cur]
        state.trans_total[prev] *= decay
        if not m:
            state.trans.pop(prev, None)
            state.trans_total.pop(prev, None)

def score_cat(state: CatState, value, cfg):
    if value is None:
        raise ValueError("cat value is None")
    cat = str(value)

    decay = float(getattr(cfg, "cat_decay", 1.0))
    _apply_decay(state, decay)

    alpha = float(getattr(cfg, "cat_smoothing_alpha", 1.0))
    eps = float(getattr(cfg, "prob_eps", 1e-9))
    novelty_min_p = float(getattr(cfg, "cat_novelty_min_prob", 0.01))

    # frequency surprisal
    k = max(1, len(state.counts))
    c = state.counts.get(cat, 0.0)
    denom = state.total + alpha * (k + 1)
    p_cat = (c + alpha) / max(eps, denom)
    score_freq = -math.log(max(eps, p_cat))

    score_trans = 0.0
    model = "categorical_surprisal"
    reason = "score_gt_threshold"

    trans_enable = bool(getattr(cfg, "cat_transition_enable", True))
    trans_w = float(getattr(cfg, "cat_transition_weight", 1.0))

    if trans_enable and state.prev is not None:
        prev = state.prev
        tcount = state.trans.get(prev, {}).get(cat, 0.0)
        ttotal = state.trans_total.get(prev, 0.0)
        kout = max(1, len(state.trans.get(prev, {})))
        denom_t = ttotal + alpha * (kout + 1)
        p_t = (tcount + alpha) / max(eps, denom_t)
        score_trans = -math.log(max(eps, p_t))
        model = "categorical_transition"

    score = score_freq + trans_w * score_trans

    # learn
    state.counts[cat] = c + 1.0
    state.total += 1.0
    if trans_enable:
        if state.prev is not None:
            prev = state.prev
            m = state.trans[prev]
            m[cat] = m.get(cat, 0.0) + 1.0
            state.trans_total[prev] += 1.0
        state.prev = cat
    else:
        state.prev = cat

    # thresholding
    state.q.update(score)
    thr = state.q.get()
    is_anom = score > thr

    # novelty rule (maps to your existing knob)
    if p_cat < novelty_min_p:
        is_anom = True
        reason = "cat_novelty_min_prob"

    # explicit new-category rule (optional)
    if getattr(cfg, "cat_new_category_is_anom", True) and c == 0.0:
        is_anom = True
        reason = "new_category"
        model = "categorical_surprisal"

    # if transition dominates, label it
    if trans_enable and (trans_w * score_trans) > score_freq:
        reason = "rare_transition"
        model = "categorical_transition"

    return score, thr, is_anom, model, reason