# BulaqML Curl API Test Suite

## Setup

``` bash
export BASE=http://localhost:8080
export UUID=test-uuid-001
```

## 1. Ingestion

### Numeric (float)

``` bash
curl -X POST $BASE/inject \
  -H "Content-Type: application/json" \
  -d '{
    "uuid": "'"$UUID"'",
    "ts": 1773855053846631,
    "value_float": 21.5
  }'
```

### Numeric (int)

``` bash
curl -X POST $BASE/inject \
  -H "Content-Type: application/json" \
  -d '{
    "uuid": "'"$UUID"'",
    "ts": 1773855053846632,
    "value_int": 100
  }'
```

### Boolean

``` bash
curl -X POST $BASE/inject \
  -H "Content-Type: application/json" \
  -d '{
    "uuid": "'"$UUID"'",
    "ts": 1773855053846633,
    "value_bool": true
  }'
```

### Categorical

``` bash
curl -X POST $BASE/inject \
  -H "Content-Type: application/json" \
  -d '{
    "uuid": "'"$UUID"'",
    "ts": 1773855053846634,
    "value_str": "RUNNING"
  }'
```

### Compact value

``` bash
curl -X POST $BASE/inject \
  -H "Content-Type: application/json" \
  -d '{
    "uuid": "'"$UUID"'",
    "ts": 1773855053846635,
    "value": 42.7
  }'
```

## Batch ingest

``` bash
curl -X POST $BASE/ingest/batch \
  -H "Content-Type: application/json" \
  -d '[
    {"uuid":"'"$UUID"'","ts":1773855053846636,"value":10},
    {"uuid":"'"$UUID"'","ts":1773855053846637,"value":12},
    {"uuid":"'"$UUID"'","ts":1773855053846638,"value":15}
  ]'
```

## Model Assignment (numeric example)

``` bash
curl -X POST $BASE/learned-tags/$UUID/assign \
  -H "Content-Type: application/json" \
  -d '{
    "assigned_model": "half_space_trees",
    "model_settings_json": {
      "model_family": "numeric",
      "model_name": "half_space_trees",
      "params": {
        "n_trees": 15,
        "height": 12,
        "window_size": 200,
        "threshold_q": 0.995,
        "warmup_min": 200
      }
    }
  }'
```

## Enable scoring

``` bash
curl -X POST $BASE/learned-tags/$UUID/enable \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "reset_runtime_state": true}'
```

## Disable scoring

``` bash
curl -X POST $BASE/learned-tags/$UUID/enable \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

## Snapshot

``` bash
curl "$BASE/snapshot?uuid=$UUID&vtype=numeric&n=100"
```

## Events

``` bash
curl "$BASE/events/recent?n=50"
```

## Stats

``` bash
curl "$BASE/stats"
```

## Config defaults

``` bash
curl "$BASE/config"
```

## Stress test

``` bash
for i in {1..50}; do
  curl -s -X POST $BASE/inject \
    -H "Content-Type: application/json" \
    -d "{\"uuid\":\"$UUID\",\"ts\":$((1773855053846631+i)),\"value\":$((RANDOM%10))}" > /dev/null
done

curl -X POST $BASE/inject \
  -H "Content-Type: application/json" \
  -d "{\"uuid\":\"$UUID\",\"ts\":1773855053999999,\"value\":999}"
```
