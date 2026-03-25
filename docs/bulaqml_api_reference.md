# BulaqML API Reference

This document describes the HTTP API exposed by the FastAPI service in `main.py`.

\---

## General Notes

* Base URL example: `http://localhost:8076` From docker host `http://bulaq-scorer:8080` from inside the container network
* Response format: JSON
* Timestamps are generally handled as **microseconds since Unix epoch**
* Value typing is inferred from one of:

  * `value\\\_float`
  * `value\\\_int`
  * `value\\\_bool`
  * `value\\\_str`

for strict typing and fallback compact field: `value` with type derived from JSON string format

* Most write routes return either:

  * `{"ok": true, ...}`
  * or an error JSON with non-200 HTTP status

\---

## Event Model

Recent events are stored in memory and returned by `/events/recent`.

Common event kinds emitted by the backend include:

* `uuid\\\_discovered`
* `runtime\\\_state\\\_created`
* `anomaly`
* `worker\\\_crash`
* `degraded`
* `error`
* `learned\\\_tag\\\_cap\\\_reached`
* `model\\\_assigned`
* `scoring\\\_state\\\_changed`
* `skipped`
* `vtype\\\_mismatch`

Anomaly events include the current triggering value and, for numeric models, optional prediction/residual fields.

\---

## 1\. Ingestion Routes

### `POST /inject`

Inject a single sample into the scoring queue.

#### Request body

```json
{
  "uuid": "demo-num-001",
  "ts": 1773855053846631,
  "value\\\_float": 21.5
}
```

Supported fields:

* `uuid` (required)
* `ts` (optional, defaults to current time in microseconds)
* one of:

  * `value\\\_float`
  * `value\\\_int`
  * `value\\\_bool`
  * `value\\\_str`
  * `value`



```curl

export BASE=http://localhost:8076

export UUID=test-uuid-001

curl -X POST $BASE/inject \\\\\\\\

\&#x20; -H "Content-Type: application/json" \\\\\\\\

\&#x20; -d '{

\&#x20;   "uuid": "'"$UUID"'",

\&#x20;   "ts": 1773855053846635,

\&#x20;   "value": 42.7

\&#x20; }'

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
\\\[
  {"uuid": "demo-num-001", "ts": 1773855053846636, "value": 10},
  {"uuid": "demo-num-001", "ts": 1773855053846637, "value": 12},
  {"uuid": "demo-num-001", "ts": 1773855053846638, "value": 15}
]
```

#### Success response

```json
{
  "accepted": 3,
  "queue\\\_depth": 17
}
```

Only valid samples are accepted; invalid ones are skipped silently in the current implementation.

``` curl
curl -X POST $BASE/ingest/batch \\\\
  -H "Content-Type: application/json" \\\\
  -d '\\\[
    {"uuid":"'"$UUID"'","ts":1773855053846636,"value":10},
    {"uuid":"'"$UUID"'","ts":1773855053846637,"value":12},
    {"uuid":"'"$UUID"'","ts":1773855053846638,"value":15}
  ]'
```





\---

## 2\. Config / Model Defaults

### `GET /config`

Returns **UI-safe model defaults only**. This is not a full internal service settings dump.

#### Response shape

```json
{
  "cfg\\\_id": 3,
  "numeric": {
    "half\\\_space\\\_trees": {
      "n\\\_trees": 15,
      "height": 12,
      "window\\\_size": 200,
      "threshold\\\_q": 0.995,
      "warmup\\\_min": 200
    },
    "ewma\\\_residual": {
      "alpha": 0.05,
      "residual\\\_threshold\\\_q": 0.995,
      "warmup\\\_min": 30,
      "min\\\_scale": 1e-06
    }
  },
  "bool": {
    "bernoulli\\\_surprisal": {
      "bool\\\_threshold\\\_q": 0.995,
      "bool\\\_alpha": 0.02,
      "bool\\\_flip\\\_rate\\\_hi": 0.2,
      "bool\\\_stuck\\\_sec": 0
    }
  },
  "cat": {
    "categorical\\\_surprisal": {
      "cat\\\_threshold\\\_q": 0.995,
      "cat\\\_decay": 0.999,
      "cat\\\_smoothing\\\_alpha": 1.0,
      "cat\\\_transition\\\_enable": true,
      "cat\\\_transition\\\_weight": 1.0,
      "cat\\\_novelty\\\_min\\\_prob": 0.01,
      "cat\\\_new\\\_category\\\_is\\\_anom": true
    }
  }
}
```

Use this route to prefill model assignment forms in the UI.

\---

## 3\. Metrics / Runtime Introspection

### `GET /metrics`

Prometheus metrics endpoint.

``` curl
export BASE=http://localhost:8076
curl "$BASE/metrics"
```


#### Response

Prometheus text exposition format.

\---

### `GET /debug/resources`

Returns process/runtime resource information.

#### Example response

```json
{
  "rss\\\_mib": 132.44,
  "cpu\\\_percent": 1.2,
  "queue\\\_depth": 0,
  "models": 17,
  "workers\\\_configured": 2,
  "workers\\\_alive": 2,
  "worker\\\_restarts": 0
}
```

\---

### `GET /stats`

Returns summarized runtime and learned-tag statistics.

#### Example response

```json
{
  "cfg\\\_id": 3,
  "runtime\\\_models": 17,
  "runtime\\\_uuid\\\_count": 11,
  "runtime\\\_numeric\\\_models": 8,
  "runtime\\\_bool\\\_models": 2,
  "runtime\\\_cat\\\_models": 1,
  "learned\\\_uuid\\\_count": 25,
  "learned\\\_discovered": 10,
  "learned\\\_assigned": 5,
  "learned\\\_active": 8,
  "learned\\\_disabled": 2,
  "snapshots": 430
}
```

\---

## 4\. Snapshot / Time-Series Inspection

### `GET /snapshot`

Returns buffered rows for a UUID from in-memory snapshot storage.

#### Query parameters

* `uuid` (required)
* `vtype` = `all | numeric | bool | cat` (default: `all`)
* `n` number of rows, capped at 5000 (default: 500)

#### Example

`GET /snapshot?uuid=demo-num-001\\\&vtype=numeric\\\&n=100`

#### Response

```json
{
  "uuid": "demo-num-001",
  "vtype": "numeric",
  "rows": \\\[
    {
      "ts": 1773952082795987,
      "uuid": "demo-num-001",
      "vtype": "numeric",
      "value": 80.0,
      "plot\\\_value": 80.0,
      "score": 439.83,
      "threshold": 0.49,
      "is\\\_anom": true,
      "reason": "residual\\\_gt\\\_threshold",
      "model": "ewma\\\_residual",
      "prediction": 50.00,
      "residual": 29.99
    }
  ],
  "enabled": true
}
```

If snapshots are disabled in settings, the route returns `enabled: false` and no rows.

\---

## 5\. Learned Tag Registry

### `GET /learned-tags`

List known learned tags.

#### Query parameters

* `q` text search
* `vtype` = `all | numeric | bool | cat`
* `status` = `all | discovered | assigned | active | disabled`
* `limit` max items

#### Example

`GET /learned-tags?q=demo\\\&vtype=numeric\\\&status=active\\\&limit=50`

#### Response

```json
{
  "items": \\\[
    {
      "uuid": "demo-num-001",
      "vtype": "numeric",
      "status": "active",
      "assigned\\\_model": "ewma\\\_residual",
      "enabled\\\_for\\\_scoring": true,
      "runtime\\\_loaded": true
    }
  ]
}
```

\---

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
    "assigned\\\_model": "ewma\\\_residual",
    "enabled\\\_for\\\_scoring": true,
    "runtime\\\_loaded": true,
    "last\\\_seen\\\_us": 1773952082795987
  }
}
```

#### Errors

* `404` if not found

\---

### `POST /learned-tags/{uuid}/assign`

Assign or update the model for a UUID.

#### Request body

```json
{
  "assigned\\\_model": "ewma\\\_residual",
  "model\\\_settings\\\_json": {
    "model\\\_family": "numeric",
    "model\\\_name": "ewma\\\_residual",
    "params": {
      "alpha": 0.05,
      "residual\\\_threshold\\\_q": 0.995,
      "warmup\\\_min": 30,
      "min\\\_scale": 0.000001
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
* emits `model\\\_assigned`

#### Success response

```json
{
  "ok": true,
  "item": {
    "uuid": "demo-num-001",
    "assigned\\\_model": "ewma\\\_residual"
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
  "reset\\\_runtime\\\_state": true
}
```

#### Behavior

* toggles `enabled\\\_for\\\_scoring`
* invalidates cache
* optionally clears runtime state
* emits `scoring\\\_state\\\_changed`

#### Success response

```json
{
  "ok": true,
  "item": {
    "uuid": "demo-num-001",
    "enabled\\\_for\\\_scoring": true
  }
}
```

\---

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
  "items": \\\[
    {
      "uuid": "demo-num-001",
      "vtypes": \\\["numeric"],
      "last\\\_seen": 1773952082795987,
      "status": "active",
      "assigned\\\_model": "ewma\\\_residual",
      "enabled\\\_for\\\_scoring": true,
      "runtime\\\_loaded": true
    }
  ]
}
```

\---

### `GET /uuid/summary`

Returns compact status and latest scoring summary for one UUID.

#### Example

`GET /uuid/summary?uuid=demo-num-001`

#### Response

```json
{
  "uuid": "demo-num-001",
  "vtypes": \\\["numeric"],
  "status": "active",
  "assigned\\\_model": "ewma\\\_residual",
  "enabled\\\_for\\\_scoring": true,
  "runtime\\\_loaded": true,
  "last\\\_seen": 1773952082795987,
  "last\\\_seen\\\_text": "2026-03-21 10:15:12",
  "recent\\\_anomaly\\\_count": 3,
  "current\\\_model": "ewma\\\_residual",
  "current\\\_score": 439.83,
  "current\\\_threshold": 0.49,
  "last\\\_prediction": 50.00,
  "last\\\_residual": 29.99
}
```

#### Errors

* `404` if UUID is not found

\---

## 7\. Model Assignment History

### `GET /model-history`

Global model history list.

#### Query parameters

* `uuid` optional filter
* `limit`

#### Example

`GET /model-history?uuid=demo-num-001\\\&limit=20`

#### Response

```json
{
  "items": \\\[
    {
      "id": 12,
      "uuid": "demo-num-001",
      "assigned\\\_model": "ewma\\\_residual",
      "assigned\\\_at": "2026-03-21T10:00:00Z"
    }
  ]
}
```

\---

### `GET /model-history/{history\\\_id}`

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
    "assigned\\\_model": "ewma\\\_residual"
  }
}
```

#### Errors

* `404` if not found

\---

### `GET /learned-tags/{uuid}/model-history`

UUID-scoped model history.

#### Example

`GET /learned-tags/demo-num-001/model-history?limit=20`

#### Response

```json
{
  "uuid": "demo-num-001",
  "items": \\\[
    {
      "id": 12,
      "assigned\\\_model": "ewma\\\_residual",
      "assigned\\\_at": "2026-03-21T10:00:00Z"
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
  "events": \\\[
    {
      "ts": 1773952082795987,
      "kind": "anomaly",
      "cfg\\\_id": 3,
      "uuid": "demo-num-001",
      "vtype": "numeric",
      "model": "ewma\\\_residual",
      "value": 80.0,
      "plot\\\_value": 80.0,
      "prediction": 50.00,
      "residual": 29.99,
      "score": 439.83,
      "threshold": 0.49,
      "reason": "residual\\\_gt\\\_threshold"
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
* `vtype\\\_mismatch` event may be emitted

### Learned-tag cap

If the maximum learned tag count is reached:

* discovery is skipped
* `learned\\\_tag\\\_cap\\\_reached` event may be emitted

\---

## 10\. Suggested API Usage Flow

Typical operator flow:

1. `POST /inject` or `POST /ingest/batch`
2. `GET /learned-tags`
3. `POST /learned-tags/{uuid}/assign`
4. `POST /learned-tags/{uuid}/enable`
5. `GET /uuid/summary`
6. `GET /snapshot`
7. `GET /events/recent`

\---

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

\---

## 12\. Status

This API is designed for a **POC / experimental online anomaly detection service** and may evolve without strict backward compatibility.

