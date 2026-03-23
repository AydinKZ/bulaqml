import asyncio
import os
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime


import psutil
from fastapi import Body, FastAPI, Request
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import JSONResponse
from river import stats as river_stats

from .metrics import *
from .model_store import TTLRUStore
from .parse import extract_value
from .scorer import (
    make_bool_state,
    make_cat_state,
    make_hst_state_from_params,
    make_ewma_state_from_params,
    score_bool,
    score_cat,
    score_numeric,
)
from .learned_tags_repo import LearnedTagsRepo
from .assignment_cache import AssignmentCache
from .settings import Settings
from .schemas import (
    ApplyConfigReq,
    SaveConfigReq,
    ApplySavedConfigReq,
    AssignModelReq,
    SetScoringReq,
)
from .kafka_client import KafkaClient
from .syslog_client import SyslogClient
from .event_bus import EventBus
from .config_registry import ConfigRegistryRepo



# -----------------------------------------------------------------------------
# App / settings / globals
# -----------------------------------------------------------------------------

app = FastAPI()
S = Settings()

CFG_LOCK = threading.Lock()
CFG = S.model_copy(deep=True)
CFG_ID = 0

Q = asyncio.Queue(maxsize=S.queue_max)
STORE = TTLRUStore(S.mdl_max_keys, S.mdl_ttl_sec)

PROC = psutil.Process()
EVENTS = deque(maxlen=int(os.getenv("EVENTS_MAX", "500")))
SNAP = defaultdict(lambda: deque(maxlen=S.snapshot_points))
LAST_SEEN: dict[str, int] = {}

WORKER_TASKS: list[asyncio.Task] = []
WORKER_RESTARTS = 0

syslog_client = SyslogClient(S)
kafka_client = KafkaClient(S)
config_repo = ConfigRegistryRepo(S)

learned_tags_repo = LearnedTagsRepo(S)
assignment_cache = AssignmentCache(ttl_sec=S.assignment_cache_ttl_sec)

def get_cfg_id():
    return CFG_ID


event_bus = EventBus(EVENTS, syslog_client, kafka_client, get_cfg_id)


# -----------------------------------------------------------------------------
# Worker / maintenance
# -----------------------------------------------------------------------------

def build_state_from_assignment(tag: dict, cfg: Settings):
    vtype = tag["vtype"]
    assigned_model = tag.get("assigned_model")
    msj = tag.get("model_settings_json") or {}
    params = dict(msj.get("params") or {})

    if vtype == "numeric":
        if assigned_model == "half_space_trees":
            params.setdefault("n_trees", cfg.n_trees)
            params.setdefault("height", cfg.height)
            params.setdefault("window_size", cfg.window_size)
            params.setdefault("threshold_q", cfg.threshold_q)
            return make_hst_state_from_params(params)

        if assigned_model == "ewma_residual":
            params.setdefault("alpha", cfg.ewma_alpha)
            params.setdefault("residual_threshold_q", cfg.ewma_residual_threshold_q)
            params.setdefault("warmup_min", cfg.ewma_warmup_min)
            params.setdefault("min_scale", cfg.ewma_min_scale)
            return make_ewma_state_from_params(params)

        raise ValueError(f"unsupported numeric assigned_model={assigned_model}")

    if vtype == "bool":
        return make_bool_state(cfg)

    if vtype == "cat":
        return make_cat_state(cfg)

    raise ValueError(f"unsupported vtype={vtype}")

def get_tag_assignment(uuid: str):
    cached = assignment_cache.get(uuid)
    if cached is not None:
        return cached

    row = learned_tags_repo.get_tag(uuid)
    if row is not None:
        assignment_cache.set(uuid, row)
    return row


def cache_put_tag(tag: dict | None):
    if tag and tag.get("uuid"):
        assignment_cache.set(tag["uuid"], tag)

def get_or_create_tag(uuid: str, vtype: str, ts: int, collector_id: str | None = None):
    tag = assignment_cache.get(uuid)
    if tag:
        return tag

    tag = learned_tags_repo.get_tag(uuid)
    if tag is None:
        tag = learned_tags_repo.upsert_discovered(
            uuid=uuid,
            vtype=vtype,
            ts=ts,
            collector_id=collector_id,
        )
        event_bus.emit(
            "uuid_discovered",
            {
                "uuid": uuid,
                "vtype": vtype,
            },
        )

    cache_put_tag(tag)
    return tag

def clear_uuid_runtime(uuid: str):
    keys = [k for k in list(STORE._data.keys()) if k.startswith(f"{uuid}|")]
    for k in keys:
        STORE._data.pop(k, None)
        STORE._last_seen.pop(k, None)
        SNAP.pop(k, None)

def spawn_worker(idx: int):
    global WORKER_RESTARTS

    async def runner():
        nonlocal idx
        try:
            await worker()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            WORKER_RESTARTS += 1
            event_bus.emit(
                "worker_crash",
                {
                    "worker_id": idx,
                    "error": repr(e),
                },
            )
            if not SHUTTING_DOWN:
                spawn_worker(idx)

    task = asyncio.create_task(runner(), name=f"worker-{idx}")
    WORKER_TASKS.append(task)


async def maintenance():
    while True:
        await asyncio.sleep(1)

        WORKER_TASKS[:] = [t for t in WORKER_TASKS if not t.done()]

        queue_depth.set(Q.qsize())
        models_total.set(len(STORE))
        update_resource_metrics()

        with CFG_LOCK:
            STORE.ttl_sec = CFG.mdl_ttl_sec

        STORE.evict_ttl()

        alive = sum(1 for t in WORKER_TASKS if not t.done())
        if alive < S.workers and not SHUTTING_DOWN:
            event_bus.emit(
                "degraded",
                {
                    "alive": alive,
                    "configured": S.workers,
                },
            )

async def worker():
    while True:
        try:
            uuid, ts, value, vtype = await Q.get()
            if vtype not in ("numeric", "bool", "cat"):
                event_bus.emit(
                    "skipped",
                    {
                        "uuid": uuid,
                        "vtype": vtype,
                        "reason": "unsupported_or_missing_vtype",
                    },
                )
                continue
        except asyncio.CancelledError:
            raise

        try:
            with CFG_LOCK:
                cfg = CFG

            store_key = f"{uuid}|{vtype}"

            # --------------------------------------------------
            # discovery / assignment lookup
            # --------------------------------------------------
            tag = get_tag_assignment(uuid)

            if tag is None:
                try:
                    tag = learned_tags_repo.upsert_discovered(
                        uuid=uuid,
                        vtype=vtype,
                        ts_us=int(ts),
                        collector_id=None,
                    )
                    assignment_cache.set(uuid, tag)
                    event_bus.emit(
                        "uuid_discovered",
                        {
                            "uuid": uuid,
                            "vtype": vtype,
                        },
                    )
                except Exception as e:
                    if "learned_tags_cap_reached" in repr(e):
                        event_bus.emit(
                            "learned_tag_cap_reached",
                            {
                                "uuid": uuid,
                                "vtype": vtype,
                                "max": S.learned_tags_max,
                            },
                        )
                        LAST_SEEN[uuid] = int(ts)
                        continue
                    raise

            learned_tags_repo.touch_seen(uuid=uuid, ts_us=int(ts), value=value)
            LAST_SEEN[uuid] = int(ts)

            # --------------------------------------------------
            # vtype consistency
            # --------------------------------------------------
            stored_vtype = tag.get("vtype")
            if stored_vtype and stored_vtype != vtype:
                event_bus.emit(
                    "vtype_mismatch",
                    {
                        "uuid": uuid,
                        "incoming_vtype": vtype,
                        "stored_vtype": stored_vtype,
                    },
                )
                continue

            # --------------------------------------------------
            # assignment gate
            # --------------------------------------------------
            assigned_model = tag.get("assigned_model")
            enabled_for_scoring = bool(tag.get("enabled_for_scoring"))

            if S.enable_assignment_gate and (not assigned_model or not enabled_for_scoring):
                continue

            # --------------------------------------------------
            # runtime state
            # --------------------------------------------------
            state = STORE.get(store_key)
            if not state:
                state = build_state_from_assignment(tag, cfg)
                STORE.set(store_key, state)
                event_bus.emit(
                    "runtime_state_created",
                    {
                        "uuid": uuid,
                        "vtype": vtype,
                        "assigned_model": assigned_model,
                    },
                )
            else:
                STORE.touch(store_key)

            # --------------------------------------------------
            # scoring
            # --------------------------------------------------
            with score_latency.time():
                if vtype == "numeric":
                    msj = tag.get("model_settings_json") or {}
                    params = dict(msj.get("params") or {})
                    score, thr, is_anom, model_name, reason = score_numeric(
                        state=state,
                        value=value,
                        params=params,
                        model_name=assigned_model,
                    )
                elif vtype == "bool":
                    score, thr, is_anom, model_name, reason = score_bool(
                        state, value, cfg, now_ts=ts / 1e6
                    )
                elif vtype == "cat":
                    score, thr, is_anom, model_name, reason = score_cat(state, value, cfg)
                else:
                    event_bus.emit(
                        "skipped",
                        {
                            "uuid": uuid,
                            "vtype": vtype,
                            "reason": "unsupported_vtype",
                        },
                    )
                    continue

            plot_value = value
            if vtype == "bool":
                plot_value = 1 if bool(value) else 0
            elif vtype == "cat":
                plot_value = None

            prediction = None
            residual = None
            if vtype == "numeric":
                prediction = getattr(state, "last_pred", None)
                residual = getattr(state, "last_residual", None)

            if cfg.enable_snapshots:
                SNAP[store_key].append(
                    {
                        "ts": int(ts),
                        "uuid": uuid,
                        "vtype": vtype,
                        "value": value,
                        "plot_value": plot_value,
                        "score": float(score),
                        "threshold": float(thr) if thr is not None else None,
                        "is_anom": bool(is_anom),
                        "reason": reason,
                        "model": model_name,
                        "prediction": prediction,
                        "residual": residual,
                    }
                )

            score_events.inc()

            if is_anom:
                event_payload = {
                    "uuid": uuid,
                    "vtype": vtype,
                    "model": model_name,
                    "score": float(score),
                    "threshold": float(thr) if thr is not None else None,
                    "reason": reason,
                    "value": value,
                    "plot_value": plot_value,
                    "ts": int(ts),
                }

                if vtype == "numeric":
                    event_payload["prediction"] = getattr(state, "last_pred", None)
                    event_payload["residual"] = getattr(state, "last_residual", None)

                score_anomalies.inc()
                event_bus.emit("anomaly", event_payload)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            try:
                if learned_tags_repo.conn is not None:
                    with learned_tags_repo.conn.cursor() as cur:
                        cur.execute(
                            """
                            update learned_tags
                            set last_error = %s,
                                updated_at = now()
                            where uuid = %s
                            """,
                            (repr(e), uuid),
                        )
            except Exception:
                pass

            event_bus.emit(
                "error",
                {
                    "uuid": uuid,
                    "vtype": vtype,
                    "err": repr(e),
                    "sample": str(value)[:120],
                },
            )
        finally:
            Q.task_done()


# -----------------------------------------------------------------------------
# Middleware / lifecycle
# -----------------------------------------------------------------------------

@app.middleware("http")
async def limit_body(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl and int(cl) > S.max_body_bytes:
        return JSONResponse({"error": "payload too large"}, status_code=413)
    return await call_next(request)


@app.on_event("startup")
async def startup():
    global MAINTENANCE_TASK, SHUTTING_DOWN

    SHUTTING_DOWN = False

    syslog_client.init()
    config_repo.init()
    learned_tags_repo.init()
    kafka_client.init()

    for i in range(S.workers):
        spawn_worker(i)

    MAINTENANCE_TASK = asyncio.create_task(maintenance(), name="maintenance")


@app.on_event("shutdown")
async def shutdown():
    global SHUTTING_DOWN

    SHUTTING_DOWN = True

    # cancel workers
    for task in WORKER_TASKS:
        if not task.done():
            task.cancel()

    # cancel maintenance
    if MAINTENANCE_TASK and not MAINTENANCE_TASK.done():
        MAINTENANCE_TASK.cancel()

    # wait for tasks to finish
    await asyncio.gather(
        *(t for t in WORKER_TASKS if t is not None),
        *([MAINTENANCE_TASK] if MAINTENANCE_TASK is not None else []),
        return_exceptions=True,
    )

    kafka_client.close()
    config_repo.close()
    learned_tags_repo.close()


# -----------------------------------------------------------------------------
# Ingest routes
# -----------------------------------------------------------------------------

@app.post("/inject")
async def inject(payload: dict = Body(...)):
    uuid = payload.get("uuid")
    ts = payload.get("ts") or int(time.time() * 1e6)

    if not uuid:
        return JSONResponse({"error": "missing uuid"}, status_code=400)
    if Q.full():
        return JSONResponse({"error": "overloaded"}, status_code=429)

    value2, vtype = extract_value(payload)
    if value2 is None or vtype is None:
        return JSONResponse(
            {
                "error": "cannot determine typed value",
                "accepted_fields": ["value", "value_bool", "value_str", "value_int", "value_float"],
            },
            status_code=400,
        )

    Q.put_nowait((uuid, ts, value2, vtype))
    return {"ok": True}


@app.post("/ingest/batch")
async def ingest_batch(payloads: list[dict] = Body(...)):
    accepted = 0
    for p in payloads:
        uuid = p.get("uuid")
        value, vtype = extract_value(p)
        if uuid and value is not None and vtype is not None and not Q.full():
            Q.put_nowait((uuid, p.get("ts", int(time.time() * 1e6)), value, vtype))
            accepted += 1

    ingest_events.inc(accepted)
    return {"accepted": accepted, "queue_depth": Q.qsize()}


# -----------------------------------------------------------------------------
# Deafult config routes
# -----------------------------------------------------------------------------


@app.get("/config")
def get_config():
    with CFG_LOCK:
        cfg_id = CFG_ID
        cfg = CFG

    return {
        "cfg_id": cfg_id,
        "numeric": {
            "half_space_trees": {
                "n_trees": cfg.n_trees,
                "height": cfg.height,
                "window_size": cfg.window_size,
                "threshold_q": cfg.threshold_q,
                "warmup_min": cfg.window_size,
            },
            "ewma_residual": {
                "alpha": cfg.ewma_alpha,
                "residual_threshold_q": cfg.ewma_residual_threshold_q,
                "warmup_min": cfg.ewma_warmup_min,
                "min_scale": cfg.ewma_min_scale,
            },
        },
        "bool": {
            "bernoulli_surprisal": {
                "bool_threshold_q": cfg.bool_threshold_q,
                "bool_alpha": cfg.bool_alpha,
                "bool_flip_rate_hi": cfg.bool_flip_rate_hi,
                "bool_stuck_sec": cfg.bool_stuck_sec,
            },
        },
        "cat": {
            "categorical_surprisal": {
                "cat_threshold_q": cfg.cat_threshold_q,
                "cat_decay": cfg.cat_decay,
                "cat_smoothing_alpha": cfg.cat_smoothing_alpha,
                "cat_transition_enable": cfg.cat_transition_enable,
                "cat_transition_weight": cfg.cat_transition_weight,
                "cat_novelty_min_prob": cfg.cat_novelty_min_prob,
                "cat_new_category_is_anom": cfg.cat_new_category_is_anom,
            },
        },
    }

# -----------------------------------------------------------------------------
# Metrics / debug / UI routes
# -----------------------------------------------------------------------------

@app.get("/metrics")
def metrics():
    return JSONResponse(generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)


@app.get("/debug/resources")
def debug_resources():
    mi = PROC.memory_info()
    alive = sum(1 for t in WORKER_TASKS if not t.done())

    return {
        "rss_mib": round(mi.rss / (1024 * 1024), 2),
        "cpu_percent": PROC.cpu_percent(interval=None),
        "queue_depth": Q.qsize(),
        "models": len(STORE),
        "workers_configured": S.workers,
        "workers_alive": alive,
        "worker_restarts": WORKER_RESTARTS,
    }


@app.get("/stats")
def get_stats():
    runtime_keys = list(STORE._data.keys()) if hasattr(STORE, "_data") else []

    runtime_uuid_set = set()
    runtime_numeric_models = 0
    runtime_bool_models = 0
    runtime_cat_models = 0

    for k in runtime_keys:
        if "|" not in k:
            continue
        uuid, vtype = k.split("|", 1)
        runtime_uuid_set.add(uuid)
        if vtype == "numeric":
            runtime_numeric_models += 1
        elif vtype == "bool":
            runtime_bool_models += 1
        elif vtype == "cat":
            runtime_cat_models += 1

    learned_total = 0
    learned_discovered = 0
    learned_assigned = 0
    learned_active = 0
    learned_disabled = 0

    try:
        rows = learned_tags_repo.list_tags(q="", vtype="all", status="all", limit=100000)
        learned_total = len(rows)
        for row in rows:
            stt = row.get("status")
            if stt == "discovered":
                learned_discovered += 1
            elif stt == "assigned":
                learned_assigned += 1
            elif stt == "active":
                learned_active += 1
            elif stt == "disabled":
                learned_disabled += 1
    except Exception:
        pass

    return {
        "cfg_id": CFG_ID,

        "runtime_models": len(STORE),
        "runtime_uuid_count": len(runtime_uuid_set),
        "runtime_numeric_models": runtime_numeric_models,
        "runtime_bool_models": runtime_bool_models,
        "runtime_cat_models": runtime_cat_models,

        "learned_uuid_count": learned_total,
        "learned_discovered": learned_discovered,
        "learned_assigned": learned_assigned,
        "learned_active": learned_active,
        "learned_disabled": learned_disabled,

        "snapshots": sum(len(v) for v in SNAP.values()) if S.enable_snapshots else 0,
    }


@app.get("/snapshot")
def get_snapshot(uuid: str, vtype: str = "all", n: int = 500):
    if not S.enable_snapshots:
        return {"uuid": uuid, "vtype": vtype, "rows": [], "enabled": False}

    rows = []
    n = max(1, min(int(n), 5000))

    if vtype == "all":
        keys = [k for k in SNAP.keys() if k.startswith(f"{uuid}|")]
    else:
        keys = [f"{uuid}|{vtype}"]

    for k in keys:
        rows.extend(list(SNAP.get(k, [])))

    rows = sorted(rows, key=lambda x: x.get("ts", 0))[-n:]
    return {"uuid": uuid, "vtype": vtype, "rows": rows, "enabled": True}

@app.get("/learned-tags")
def learned_tags_list(q: str = "", vtype: str = "all", status: str = "all", limit: int = 100):
    try:
        items = learned_tags_repo.list_tags(q=q, vtype=vtype, status=status, limit=limit)
        for item in items:
            item["runtime_loaded"] = f"{item['uuid']}|{item['vtype']}" in STORE._data
        return {"items": items}
    except Exception as e:
        return JSONResponse({"ok": False, "error": repr(e)}, status_code=400)

@app.get("/learned-tags/{uuid}")
def learned_tag_get(uuid: str):
    try:
        row = learned_tags_repo.get_tag(uuid)
        if not row:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

        row["runtime_loaded"] = f"{row['uuid']}|{row['vtype']}" in STORE._data
        row["last_seen_us"] = LAST_SEEN.get(uuid)
        return {"ok": True, "item": row}
    except Exception as e:
        return JSONResponse({"ok": False, "error": repr(e)}, status_code=400)

@app.post("/learned-tags/{uuid}/assign")
def assign_model(uuid: str, req: AssignModelReq):
    try:
        row = learned_tags_repo.assign_model(
            uuid=uuid,
            assigned_model=req.assigned_model,
            model_settings_json=req.model_settings_json,
            actor=req.actor,
            source=req.source,
        )

        assignment_cache.invalidate(uuid)
        clear_uuid_runtime(uuid)

        event_bus.emit(
            "model_assigned",
            {
                "uuid": uuid,
                "assigned_model": req.assigned_model,
                "source": req.source,
            },
        )

        return {"ok": True, "item": row}
    except Exception as e:
        return JSONResponse({"ok": False, "error": repr(e)}, status_code=400)

@app.post("/learned-tags/{uuid}/enable")
def set_scoring(uuid: str, req: SetScoringReq):
    try:
        row = learned_tags_repo.set_enabled(
            uuid=uuid,
            enabled=req.enabled,
            actor=req.actor,
            source=req.source,
        )

        assignment_cache.invalidate(uuid)

        if req.reset_runtime_state:
            clear_uuid_runtime(uuid)

        event_bus.emit(
            "scoring_state_changed",
            {
                "uuid": uuid,
                "enabled": req.enabled,
                "source": req.source,
            },
        )

        return {"ok": True, "item": row}
    except Exception as e:
        return JSONResponse({"ok": False, "error": repr(e)}, status_code=400)


@app.get("/uuids")
def uuids(q: str = "", vtype: str = "all", limit: int = 100):
    try:
        items = learned_tags_repo.list_tags(q=q, vtype=vtype, status="all", limit=limit)
        out = []
        for item in items:
            out.append(
                {
                    "uuid": item["uuid"],
                    "vtypes": [item["vtype"]],
                    "last_seen": LAST_SEEN.get(item["uuid"]),
                    "status": item.get("status"),
                    "assigned_model": item.get("assigned_model"),
                    "enabled_for_scoring": item.get("enabled_for_scoring"),
                    "runtime_loaded": f"{item['uuid']}|{item['vtype']}" in STORE._data,
                }
            )
        return {"items": out}
    except Exception as e:
        return JSONResponse({"ok": False, "error": repr(e)}, status_code=400)


@app.get("/uuid/summary")
def uuid_summary(uuid: str):
    try:
        tag = learned_tags_repo.get_tag(uuid)
        if not tag:
            return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

        current_model = None
        current_score = None
        current_threshold = None
        recent_anomaly_count = 0

        for e in EVENTS:
            if e.get("uuid") == uuid and e.get("kind") == "anomaly":
                recent_anomaly_count += 1
                if current_model is None:
                    current_model = e.get("model")
                    current_score = e.get("score")
                    current_threshold = e.get("threshold")

        last_seen = LAST_SEEN.get(uuid)
        runtime_key = f"{tag['uuid']}|{tag['vtype']}"
        state = STORE.get(runtime_key)

        return {
            "uuid": uuid,
            "vtypes": [tag["vtype"]],
            "status": tag.get("status"),
            "assigned_model": tag.get("assigned_model"),
            "enabled_for_scoring": tag.get("enabled_for_scoring"),
            "runtime_loaded": runtime_key in STORE._data,

            "last_seen": last_seen,
            "last_seen_text": (
                datetime.fromtimestamp(last_seen / 1_000_000, UTC).strftime("%Y-%m-%d %H:%M:%S")
                if last_seen
                else "-"
            ),

            "recent_anomaly_count": recent_anomaly_count,
            "current_model": current_model,
            "current_score": current_score,
            "current_threshold": current_threshold,

            "last_prediction": getattr(state, "last_pred", None) if state else None,
            "last_residual": getattr(state, "last_residual", None) if state else None,
        }
    except Exception as e:
        return JSONResponse({"ok": False, "error": repr(e)}, status_code=400)

@app.get("/model-history")
def model_history_list(uuid: str = "", limit: int = 100):
    try:
        items = learned_tags_repo.list_model_history(uuid=uuid, limit=limit)
        return {"items": items}
    except Exception as e:
        return JSONResponse({"ok": False, "error": repr(e)}, status_code=400)

@app.get("/model-history/{history_id}")
def model_history_get(history_id: int):
    try:
        item = learned_tags_repo.get_model_history_item(history_id)
        return {"ok": True, "item": item}
    except Exception as e:
        return JSONResponse({"ok": False, "error": repr(e)}, status_code=404)

@app.get("/learned-tags/{uuid}/model-history")
def learned_tag_model_history(uuid: str, limit: int = 100):
    try:
        items = learned_tags_repo.list_model_history(uuid=uuid, limit=limit)
        return {"uuid": uuid, "items": items}
    except Exception as e:
        return JSONResponse({"ok": False, "error": repr(e)}, status_code=400)

@app.get("/events/recent")
def events_recent(n: int = 50):
    n = max(1, min(int(n), 500))
    return {"events": list(EVENTS)[:n]}