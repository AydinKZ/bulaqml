## 🌊 BulaqML — Streaming Anomaly Detection (POC)

BulaqML is a beginner-friendly proof of concept for building a real-time anomaly detection service using online (streaming) machine learning with [River ML library ](https://riverml.xyz/latest/).

It is a per-signal anomaly detection workflow where each signal (UUID/tag):

- is discovered automatically,
- can be assigned its own anomaly detection model,
- moves through a simple lifecycle: **discovered → assigned → actively scored**,
- can emit anomaly events through the web UI, REST API, Kafka, or Syslog.

It also includes a built-in LLM assistant layer for anomaly review and detector tuning using your own API key.

---

## ⚠️ Not Production Ready

This project is a proof of concept and is **not** production-ready.

It currently lacks several production-grade capabilities, including hardening, full security controls, and more complete pre-processing and post-processing features. That said, it is still fun sandbox for experimenting with online anomaly detection and can be integrated with observability tools such as Grafana or Elastic.

---

## 🚀 Quick Start

### Prerequisites

Make sure you have the following installed:

- Docker
- Docker Compose plugin (`docker compose`)

### Start the stack

From the repository root, run:

#### Linux / macOS
```bash
docker compose -f bulaq-compose-git.yml up -d --build
```
#### Powershell
```
docker compose -f .\bulaq-compose-git.yml up -d --build
```
#### Windows CMD
```
docker compose -f bulaq-compose-git.yml up -d --build
```

stop the stack
```bash
docker compose -f bulaq-compose-git.yml down
```
---
#### Access the services

After startup, open:

- Web UI: http://localhost:8501
- REST API: http://localhost:8076

The 🚇metro-hel-mqtt container starts automatically and feeds live Helsinki Metro test data into the system.

Typical first steps:

- Open the web UI.
- Select a discovered tag.
- Assign a model.
- Enable scoring.
- Observe anomalies and runtime metrics.

To enable Kafka or Syslog forwarding, edit the relevant environment variables in bulaq-compose-git.yml before starting the stack.

---

###📘 REST API Reference and test scripts

A separate REST API README is [available here ](docs/bulaqml_api_reference.md)

If you don't like the metro example, additional test sets using curl are [documented here](docs/bulaqml_curl_tests.md)

---
📡 Example Input
```JSON
{
  "ts": 1773855053846631,
  "uuid": "device-temp-001",
  "value": 21.5
}
```

Refer to the REST API documentation for batch ingestion and typed ingestion examples.

🚨 Example Anomaly Event

```JSON
{
  "ts": 1773952082795987,
  "kind": "anomaly",
  "uuid": "device-temp-001",
  "vtype": "numeric",
  "model": "ewma_residual",
  "value": 80.0,
  "score": 439.83,
  "threshold": 0.49,
  "reason": "residual_gt_threshold"
}
```

---
### 🚇 metro-hel-mqtt
metro-hel-mqtt is an auxiliary test container that forwards real-time Helsinki Metro data into BulaqML.
It is a lightweight ingestion bridge that subscribes to the Helsinki HFP (High Frequency Positioning) MQTT feed, dynamically learns time-series tags, and converts selected JSON fields into individual signal streams.
Each metric, such as speed, latitude, longitude, or route, is mapped to a stable signal identity derived from the MQTT topic:(`/hfp/.../metro/<oper>/<veh>/<field>`), with optional compact identifiers like `hfp.metro.oper_50.veh_137.spd`. The bridge maintains an in-memory and CSV-backed tag registry and generates deterministic UUIDs using `xxh3`.

Useful frequently changing fields include:

- Numeric: spd, lat, long, hdg
- Categorical: route

The feed does not naturally provide many useful boolean examples, so boolean testing is better done through manual REST examples.
If you feel dedicated enough you can even try to score more dense traffic from busses and trams.
More details on HFP API data structure in [their documentation] (https://digitransit.fi/en/developers/apis/5-realtime-api/vehicle-positions/high-frequency-positioning/#examples)

---

## ⚙️ Features

- ✅ Per-UUID model assignment
- ✅ Online learning (no retraining)
- ✅ REST ingestion API
- ✅ Event-based anomaly reporting
- ✅ Model assignment history (PostgreSQL)
- ✅ Lightweight Streamlit UI
- ✅ Runtime stats and monitoring

---
### GUI examples
---
## Architecture


---

## 🧩 Implemented Models

### 🔢 Numeric (time-series)

#### 1. Half-Space Trees (HST)
- Model: `half_space_trees`
- Type: tree-based unsupervised anomaly detection 
- Notes: includes a warm-up period of about 200 observations before anomaly flagging starts
- Good for:
  - general-purpose numeric anomaly detection
  - distribution shifts

**Parameters:**
- `n_trees`
- `height`
- `window_size`
- `threshold_q`

---

#### 2. EWMA Residual Model
- Model: `ewma_residual`
- Type: forecasting + residual anomaly detection
- Good for:
  - smooth signals
  - trend-aware detection

**Parameters:**
- `alpha`
- `residual_threshold_q`
- `warmup_min`
- `min_scale`

---

### 🔘 Boolean (binary signals)

#### 3. Bernoulli Surprisal
- Model: `bernoulli_surprisal`

Detects:
- chatter (frequent flips)
- stuck signals
- probability shifts

**Parameters:**
- `bool_threshold_q`
- `bool_alpha`
- `bool_flip_rate_hi`
- `bool_stuck_sec`

---

### 🔤 Categorical

#### 4. Categorical Surprisal
- Model: `categorical_surprisal`

Detects:
- rare categories
- unseen values
- abnormal transitions

**Parameters:**
- `cat_threshold_q`
- `cat_decay`
- `cat_smoothing_alpha`
- `cat_transition_enable`
- `cat_transition_weight`
- `cat_novelty_min_prob`
- `cat_new_category_is_anom`

---

###💡 Why Bulaq?

“Bulaq” means brook or small stream in Kazakh:

The project’s intent is a smaller and simpler stream ML-wrapper of River framework, focused specifically on anomaly detection.
