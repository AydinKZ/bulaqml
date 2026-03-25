# BulaqML API Reference

This document describes the HTTP API exposed by the FastAPI service in `main.py`.


## General Notes

* Base URL example: `http://localhost:8076` From docker host `http://bulaq-scorer:8080` from inside the container network
* Response format: JSON
* Timestamps are generally handled as **microseconds since Unix epoch**
* Value typing is inferred from one of:

  * `value_float`
  * `value_int`
  * `value_bool`
  * `value_str`

for strict typing 
and fallback compact field: `value` 
with type derived from JSON string format

* Most write routes return either:

  * `{"ok": true, ...}`
  * or an error JSON with non-200 HTTP status

---

## Event Model

Recent events are stored in memory and returned by `/events/recent`.

```json
export BASE=http://localhost:8076
curl "$BASE/events/recent"
```

Common event kinds emitted by the backend include:

* `uuid_discovered`
* `runtime_state_created`
* `anomaly`
* `worker_crash`
* `degraded`
* `error`
* `learned_tag_cap_reached`
* `model_assigned`
* `scoring_state_changed`
* `skipped`
* `vtype_mismatch`

Anomaly events include the current triggering value and, for numeric models, optional prediction/residual fields.

---

## 1\. Ingestion Routes

### `POST /inject`

Inject a single sample into the scoring queue.

#### Request body

```json
{
  "uuid": "demo-num-001",
  "ts": 1773855053846631,
  "value_float": 21.5
}
```

Supported fields:

* `uuid` (required)
* `ts` (optional, defaults to current time in microseconds)
* one of:

  * `value_float`
  * `value_int`
  * `value_bool`
  * `value_str`
  * `value`



```json

export BASE=http://localhost:8076

export UUID=test-uuid-001

curl -X POST $BASE/inject \
  -H "Content-Type: application/json" \
  -d '{
    "uuid": "'"$UUID"'",
    "ts": 1773855053846635,
    "value": 42.7
  }'
```


#### Success response

```json
{
  "ok": true
}
```

#### Error cases

* `400` if `uuid` is missing
* `400` if value type cannot be determined
* `429` if the queue is full

\---

### `POST /ingest/batch`

Inject multiple samples in one request.

#### Request body

```json
[
  {"uuid": "demo-num-001", "ts": 1773855053846636, "value": 10},
  {"uuid": "demo-num-001", "ts": 1773855053846637, "value": 12},
  {"uuid": "demo-num-001", "ts": 1773855053846638, "value": 15}
]
```

#### Success response

```json
{
  "accepted": 3,
  "queue_depth": 17
}
```

Only valid samples are accepted; invalid ones are skipped silently in the current implementation.

```json
curl -X POST $BASE/ingest/batch \
  -H "Content-Type: application/json" \
  -d '\\\[
    {"uuid":"'"$UUID"'","ts":1773855053846636,"value":10},
    {"uuid":"'"$UUID"'","ts":1773855053846637,"value":12},
    {"uuid":"'"$UUID"'","ts":1773855053846638,"value":15}
  ]'
```

## 2\. Config / Model Defaults

### `GET /config`

Returns **UI-safe model defaults only**. This is not a full internal service settings dump.

#### Response shape

```json
{
  "cfg_id": 3,
  "numeric": {
    "half_space_trees": {
      "n_trees": 15,
      "height": 12,
      "window_size": 200,
      "threshold_q": 0.995,
      "warmup_min": 200
    },
    "ewma_residual": {
      "alpha": 0.05,
      "residual_threshold_q": 0.995,
      "warmup_min": 30,
      "min_scale": 1e-06
    }
  },
  "bool": {
    "bernoulli_surprisal": {
      "bool_threshold_q": 0.995,
      "bool_alpha": 0.02,
      "bool_flip_rate_hi": 0.2,
      "bool_stuck_sec": 0
    }
  },
  "cat": {
    "categorical_surprisal": {
      "cat_threshold_q": 0.995,
      "cat_decay": 0.999,
      "cat_smoothing_alpha": 1.0,
      "cat_transition_enable": true,
      "cat_transition_weight": 1.0,
      "cat_novelty_min_prob": 0.01,
      "cat_new_category_is_anom": true
    }
  }
}
```

Use this route to prefill model assignment forms in the UI.

---

## 3\. Metrics / Runtime Introspection

### `GET /metrics`

Prometheus metrics endpoint.


#### Response

Prometheus text exposition format.


### `GET /debug/resources`

Returns process/runtime resource information.

#### Example response

```json
{
  "rss_mib": 132.44,
  "cpu_percent": 1.2,
  "queue_depth": 0,
  "models": 17,
  "workers_configured": 2,
  "workers_alive": 2,
  "worker_restarts": 0
}
```



### `GET /stats`

Returns summarized runtime and learned-tag statistics.

#### Example response

```json
{
  "cfg_id": 3,
  "runtime_models": 17,
  "runtime_uuid_count": 11,
  "runtime_numeric_models": 8,
  "runtime_bool_models": 2,
  "runtime_cat_models": 1,
  "learned_uuid_count": 25,
  "learned_discovered": 10,
  "learned_assigned": 5,
  "learned_active": 8,
  "learned_disabled": 2,
  "snapshots": 430
}
```



## 4\. Snapshot / Time-Series Inspection

### `GET /snapshot`

Returns buffered rows for a UUID from in-memory snapshot storage.

#### Query parameters

* `uuid` (required)
* `vtype` = `all | numeric | bool | cat` (default: `all`)
* `n` number of rows, capped at 5000 (default: 500)

#### Example

`GET /snapshot?uuid=demo-num-001&vtype=numeric&n=100`

#### Response

```json
{
  "uuid": "demo-num-001",
  "vtype": "numeric",
  "rows": [
    {
      "ts": 1773952082795987,
      "uuid": "demo-num-001",
      "vtype": "numeric",
      "value": 80.0,
      "plot_value": 80.0,
      "score": 439.83,
      "threshold": 0.49,
      "is_anom": true,
      "reason": "residual_gt_threshold",
      "model": "ewma_residual",
      "prediction": 50.00,
      "residual": 29.99
    }
  ],
  "enabled": true
}
```

If snapshots are disabled in settings, the route returns `enabled: false` and no rows.


## 5\. Learned Tag Registry

### `GET /learned-tags`

List known learned tags.

#### Query parameters

* `q` text search
* `vtype` = `all | numeric | bool | cat`
* `status` = `all | discovered | assigned | active | disabled`
* `limit` max items

#### Example

`GET /learned-tags?q=demo&vtype=numeric&status=active&limit=50`

#### Response

```json
{
  "items": [
    {
      "uuid": "demo-num-001",
      "vtype": "numeric",
      "status": "active",
      "assigned_model": "ewma_residual",
      "enabled_for_scoring": true,
      "runtime_loaded": true
    }
  ]
}
```


### `GET /learned-tags/{uuid}`

Return one learned tag.

#### Example

`GET /learned-tags/demo-num-001`

#### Response

```json
{
  "ok": true,
  "item": {
    "uuid": "demo-num-001",
    "vtype": "numeric",
    "status": "active",
    "assigned_model": "ewma_residual",
    "enabled_for_scoring": true,
    "runtime_loaded": true,
    "last_seen_us": 1773952082795987
  }
}
```

#### Errors

* `404` if not found


### `POST /learned-tags/{uuid}/assign`

Assign or update the model for a UUID.

#### Request body

```json
{
  "assigned_model": "ewma_residual",
  "model_settings_json": {
    "model_family": "numeric",
    "model_name": "ewma_residual",
    "params": {
      "alpha": 0.05,
      "residual_threshold_q": 0.995,
      "warmup_min": 30,
      "min_scale": 0.000001
    }
  },
  "actor": "ui",
  "source": "ui"
}
```

#### Behavior

* updates learned tag assignment
* invalidates cached assignment
* clears runtime state for that UUID
* emits `model_assigned`

#### Success response

```json
{
  "ok": true,
  "item": {
    "uuid": "demo-num-001",
    "assigned_model": "ewma_residual"
  }
}
```

\---

### `POST /learned-tags/{uuid}/enable`

Enable or disable scoring for a UUID.

#### Request body

```json
{
  "enabled": true,
  "actor": "ui",
  "source": "ui",
  "reset_runtime_state": true
}
```

#### Behavior

* toggles `enabled_for_scoring`
* invalidates cache
* optionally clears runtime state
* emits `scoring_state_changed`

#### Success response

```json
{
  "ok": true,
  "item": {
    "uuid": "demo-num-001",
    "enabled_for_scoring": true
  }
}
```


## 6\. UUID-Oriented Convenience Routes

### `GET /uuids`

Legacy/convenience listing route.

#### Query parameters

* `q`
* `vtype`
* `limit`

#### Response

```json
{
  "items": [
    {
      "uuid": "demo-num-001",
      "vtypes": ["numeric"],
      "last_seen": 1773952082795987,
      "status": "active",
      "assigned_model": "ewma_residual",
      "enabled_for_scoring": true,
      "runtime_loaded": true
    }
  ]
}
```



### `GET /uuid/summary`

Returns compact status and latest scoring summary for one UUID.

#### Example

`GET /uuid/summary?uuid=demo-num-001`

#### Response

```json
{
  "uuid": "demo-num-001",
  "vtypes": ["numeric"],
  "status": "active",
  "assigned_model": "ewma_residual",
  "enabled_for_scoring": true,
  "runtime_loaded": true,
  "last_seen": 1773952082795987,
  "last_seen_text": "2026-03-21 10:15:12",
  "recent_anomaly_count": 3,
  "current_model": "ewma_residual",
  "current_score": 439.83,
  "current_threshold": 0.49,
  "last_prediction": 50.00,
  "last_residual": 29.99
}
```

#### Errors

* `404` if UUID is not found



## 7\. Model Assignment History

### `GET /model-history`

Global model history list.

#### Query parameters

* `uuid` optional filter
* `limit`

#### Example

`GET /model-history?uuid=demo-num-001&limit=20`

#### Response

```json
{
  "items": [
    {
      "id": 12,
      "uuid": "demo-num-001",
      "assigned_model": "ewma_residual",
      "assigned_at": "2026-03-21T10:00:00Z"
    }
  ]
}
```



### `GET /model-history/{history_id}`

Return one history record.

#### Example

`GET /model-history/12`

#### Response

```json
{
  "ok": true,
  "item": {
    "id": 12,
    "uuid": "demo-num-001",
    "assigned_model": "ewma_residual"
  }
}
```

#### Errors

* `404` if not found



### `GET /learned-tags/{uuid}/model-history`

UUID-scoped model history.

#### Example

`GET /learned-tags/demo-num-001/model-history?limit=20`

#### Response

```json
{
  "uuid": "demo-num-001",
  "items": [
    {
      "id": 12,
      "assigned_model": "ewma_residual",
      "assigned_at": "2026-03-21T10:00:00Z"
    }
  ]
}
```

\---

## 8\. Recent Events

### `GET /events/recent`

Returns recent in-memory events.

#### Query parameters

* `n` max events, range 1..500

#### Example

`GET /events/recent?n=100`

#### Response

```json
{
  "events": [
    {
      "ts": 1773952082795987,
      "kind": "anomaly",
      "cfg_id": 3,
      "uuid": "demo-num-001",
      "vtype": "numeric",
      "model": "ewma_residual",
      "value": 80.0,
      "plot_value": 80.0,
      "prediction": 50.00,
      "residual": 29.99,
      "score": 439.83,
      "threshold": 0.49,
      "reason": "residual_gt_threshold"
    }
  ]
}
```

\---

## 9\. Operational Behavior Notes

### Assignment gate

If assignment gating is enabled:

* newly discovered UUIDs are tracked
* they are **not scored** until assigned + enabled

### Runtime state creation

Runtime state is created lazily on the first eligible sample after assignment/enabling.

### Value / type mismatch

If incoming type conflicts with stored type:

* scoring is skipped
* `vtype_mismatch` event may be emitted

### Learned-tag cap

If the maximum learned tag count is reached:

* discovery is skipped
* `learned_tag_cap_reached` event may be emitted



## 10\. Suggested API Usage Flow

Typical operator flow:

1. `POST /inject` or `POST /ingest/batch`
2. `GET /learned-tags`
3. `POST /learned-tags/{uuid}/assign`
4. `POST /learned-tags/{uuid}/enable`
5. `GET /uuid/summary`
6. `GET /snapshot`
7. `GET /events/recent`



## 11\. Notes for UI / Integrators

The frontend should primarily rely on:

* `/config`
* `/stats`
* `/debug/resources`
* `/learned-tags`
* `/learned-tags/{uuid}`
* `/learned-tags/{uuid}/assign`
* `/learned-tags/{uuid}/enable`
* `/learned-tags/{uuid}/model-history`
* `/uuid/summary`
* `/snapshot`
* `/events/recent`


## 12\. Status

This API is designed for a **POC / experimental online anomaly detection service** and may evolve without strict backward compatibility.

