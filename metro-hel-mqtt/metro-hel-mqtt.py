#!/usr/bin/env python3
"""
hfp_metro_to_rest.py

Subscribe to Helsinki HFP metro MQTT feed, learn historian-style tags in memory,
persist newly discovered tags to CSV, and POST each arriving value batch to REST.

Tag path style:
    /hfp/v2/journey/ongoing/vp/metro/0050/00137/spd

UUID format:
    <collector_id>-<20-digit-xxh3_64-decimal>

REST batch payload format:
[
  {
    "uuid": "collector-00000000000000012345",
    "ts": 1773679658000000,
    "value": 20.34
  },
  ...
]

Behavior:
- subscribes to /hfp/v2/journey/ongoing/vp/metro/#
- flattens JSON under VP
- creates one tag per JSON key except timestamp fields
- skips tst and tsi from tag creation
- optionally skips null values
- keeps learned tag registry in memory
- appends new tags to CSV
- sends one HTTP batch per MQTT message

Dependencies:
    pip install paho-mqtt requests xxhash
"""

from __future__ import annotations

import os
import csv
import json
import logging
import signal
import ssl
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional, Tuple

import paho.mqtt.client as mqtt
import requests
import xxhash


# ============================================================================
# Configuration
# ============================================================================

COLLECTOR_ID = os.getenv("COLLECTOR_ID", "bulaq-metro")

IDENTITY_MODE = os.getenv("IDENTITY_MODE", "compact_path")  # "uuid" or "compact_path"

MQTT_HOST = os.getenv("MQTT_HOST", "mqtt.hsl.fi")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "/hfp/v2/journey/ongoing/vp/metro/#")
MQTT_KEEPALIVE = int(os.getenv("MQTT_KEEPALIVE", "60"))
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", f"{COLLECTOR_ID}-{int(time.time())}")
MQTT_QOS_OUT = int(os.getenv("MQTT_QOS_OUT", "0"))

REST_URL = os.getenv("REST_URL", "http://bulaq-scorer:8080/ingest/batch")
REST_TIMEOUT_SEC = int(os.getenv("REST_TIMEOUT_SEC", "15"))

LEARNED_TAGS_CSV = os.getenv("LEARNED_TAGS_CSV", "/data/learned_tags.csv")
POST_ERRORS_CSV = os.getenv("POST_ERRORS_CSV", "/data/post_errors.csv")

SKIP_KEYS = {"tst", "tsi"}
POST_NULL_VALUES = os.getenv("POST_NULL_VALUES", "false").lower() == "true"

HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "2"))
HTTP_RETRY_BACKOFF_SEC = float(os.getenv("HTTP_RETRY_BACKOFF_SEC", "1.0"))

# ============================================================================
# Logging
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("hfp_metro_to_rest")


# ============================================================================
# Data model
# ============================================================================

@dataclass
class LearnedTag:
    uuid: str
    collector_id: str
    tag_path: str
    json_field: str
    json_path: str
    mqtt_base_topic: str
    oper: str
    veh: str
    transport_mode: str
    first_seen_ts: str
    last_seen_ts: str


# ============================================================================
# Helpers
# ============================================================================

def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_tag_uuid(*, collector_id: str, tag_path: str) -> str:
    """
    xxh3_64 -> unsigned 64-bit int -> decimal zero-padded to 20 digits
    """
    digest_int = xxhash.xxh3_64_intdigest(tag_path)
    return f"{collector_id}-{digest_int:020d}"


def parse_event_ts_to_us(vp: dict) -> int:
    """
    Return event timestamp in Unix microseconds.

    Priority:
    1. tst ISO8601 string
    2. tsi Unix seconds
    3. current UTC time
    """
    tst = vp.get("tst")
    if isinstance(tst, str) and tst:
        dt = datetime.fromisoformat(tst.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1_000_000)

    tsi = vp.get("tsi")
    if isinstance(tsi, (int, float)):
        return int(float(tsi) * 1_000_000)

    return int(datetime.now(timezone.utc).timestamp() * 1_000_000)


def flatten_json(obj: Any, prefix: str = "") -> Iterable[Tuple[str, Any]]:
    """
    Flatten nested JSON into dotted paths.

    Example:
        {"a": {"b": 1}, "c": 2}
    -> ("a.b", 1), ("c", 2)
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            next_prefix = f"{prefix}.{k}" if prefix else k
            yield from flatten_json(v, next_prefix)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            next_prefix = f"{prefix}[{i}]"
            yield from flatten_json(v, next_prefix)
    else:
        yield prefix, obj


def parse_hfp_topic(topic: str) -> Dict[str, str]:
    """
    Expected topic example:
    /hfp/v2/journey/ongoing/vp/metro/0050/00137/31M1/2/Kivenlahti/18:07/2314602/0/60;24/17/64/15

    We use stable prefix until vehicle:
    /hfp/v2/journey/ongoing/vp/metro/<oper>/<veh>/...
    """
    parts = topic.strip("/").split("/")
    if len(parts) < 8:
        raise ValueError(f"Unexpected HFP topic, too short: {topic}")

    return {
        "prefix": parts[0],
        "version": parts[1],
        "journey_type": parts[2],
        "temporal_type": parts[3],
        "event_type": parts[4],
        "transport_mode": parts[5],
        "oper": parts[6],
        "veh": parts[7],
    }


def build_tag_path_from_topic(topic_meta: Dict[str, str], field_name: str) -> str:
    return (
        f"/{topic_meta['prefix']}/{topic_meta['version']}/{topic_meta['journey_type']}/"
        f"{topic_meta['temporal_type']}/{topic_meta['event_type']}/{topic_meta['transport_mode']}/"
        f"{topic_meta['oper']}/{topic_meta['veh']}/{field_name}"
    )


def append_error_csv(row: Dict[str, Any]) -> None:
    path = Path(POST_ERRORS_CSV)
    file_exists = path.exists()

    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "ts",
                "status_code",
                "error",
                "response_text",
                "payload",
            ],
        )
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

def build_compact_identity(topic_meta: Dict[str, str], field_name: str) -> str:
    """
    Build compact identity string to be sent in the 'uuid' field, for example:
        hfp.metro.oper_50.veh_137.spd
    """
    oper_int = int(topic_meta["oper"])
    veh_int = int(topic_meta["veh"])
    return f"hfp.{topic_meta['transport_mode']}.oper_{oper_int}.veh_{veh_int}.{field_name}"

def resolve_outbound_identity(
    *,
    identity_mode: str,
    learned_uuid: str,
    topic_meta: Dict[str, str],
    field_name: str,
) -> str:
    if identity_mode == "uuid":
        return learned_uuid
    if identity_mode == "compact_path":
        return build_compact_identity(topic_meta, field_name)
    raise ValueError(f"Unsupported IDENTITY_MODE: {identity_mode}")



# ============================================================================
# Learned tag registry
# ============================================================================

class LearnedTagRegistry:
    def __init__(self, csv_path: str):
        self.csv_path = Path(csv_path)
        self.tags: Dict[str, LearnedTag] = {}
        self.lock = Lock()
        self._ensure_csv_header()
        self._load_existing()

    def _ensure_csv_header(self) -> None:
        if self.csv_path.exists():
            return

        with self.csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "uuid",
                    "collector_id",
                    "tag_path",
                    "json_field",
                    "json_path",
                    "mqtt_base_topic",
                    "oper",
                    "veh",
                    "transport_mode",
                    "first_seen_ts",
                    "last_seen_ts",
                ],
            )
            writer.writeheader()

    def _load_existing(self) -> None:
        if not self.csv_path.exists():
            return

        with self.csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                tag = LearnedTag(**row)
                self.tags[tag.tag_path] = tag

        logger.info("Loaded %d learned tags from %s", len(self.tags), self.csv_path)

    def upsert_new_if_missing(
        self,
        *,
        tag_path: str,
        json_field: str,
        json_path: str,
        mqtt_base_topic: str,
        oper: str,
        veh: str,
        transport_mode: str,
        now_iso: str,
        collector_id: str,
    ) -> LearnedTag:
        with self.lock:
            existing = self.tags.get(tag_path)
            if existing:
                existing.last_seen_ts = now_iso
                return existing

            tag_uuid = build_tag_uuid(collector_id=collector_id, tag_path=tag_path)
            tag = LearnedTag(
                uuid=tag_uuid,
                collector_id=collector_id,
                tag_path=tag_path,
                json_field=json_field,
                json_path=json_path,
                mqtt_base_topic=mqtt_base_topic,
                oper=oper,
                veh=veh,
                transport_mode=transport_mode,
                first_seen_ts=now_iso,
                last_seen_ts=now_iso,
            )
            self.tags[tag_path] = tag
            self._append_csv(tag)
            logger.info("Learned new tag: %s -> %s", tag_path, tag_uuid)
            return tag

    def _append_csv(self, tag: LearnedTag) -> None:
        with self.csv_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "uuid",
                    "collector_id",
                    "tag_path",
                    "json_field",
                    "json_path",
                    "mqtt_base_topic",
                    "oper",
                    "veh",
                    "transport_mode",
                    "first_seen_ts",
                    "last_seen_ts",
                ],
            )
            writer.writerow(asdict(tag))


# ============================================================================
# HTTP posting
# ============================================================================

def post_batch(session: requests.Session, payload: List[Dict[str, Any]]) -> None:
    """
    Exact batch format expected by your backend:
    [
      {
        "uuid": "...",
        "ts": 1710000000000000,
        "value": 10.5
      }
    ]
    """
    if not payload:
        return

    last_exc: Optional[Exception] = None
    last_status: Optional[int] = None
    last_text: Optional[str] = None

    for attempt in range(HTTP_RETRIES + 1):
        try:
            resp = session.post(REST_URL, json=payload, timeout=REST_TIMEOUT_SEC)
            last_status = resp.status_code
            last_text = resp.text[:1000]
            if 200 <= resp.status_code < 300:
                return
            raise requests.HTTPError(f"HTTP {resp.status_code}: {resp.text[:500]}")
        except Exception as exc:
            last_exc = exc
            if attempt < HTTP_RETRIES:
                time.sleep(HTTP_RETRY_BACKOFF_SEC * (attempt + 1))

    append_error_csv(
        {
            "ts": utcnow_iso(),
            "status_code": last_status,
            "error": repr(last_exc),
            "response_text": last_text,
            "payload": json.dumps(payload, ensure_ascii=False),
        }
    )
    logger.error("Batch POST failed: %s", last_exc)


# ============================================================================
# Collector
# ============================================================================

class HfpMetroCollector:
    def __init__(self):
        self.registry = LearnedTagRegistry(LEARNED_TAGS_CSV)
        self.http = requests.Session()

        self.client = mqtt.Client(
            client_id=MQTT_CLIENT_ID,
            clean_session=True,
            protocol=mqtt.MQTTv311,
        )

        self.client.tls_set(
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
        self.client.tls_insecure_set(False)

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

        self._stop = False

    def start(self) -> None:
        logger.info("Connecting to MQTT %s:%s", MQTT_HOST, MQTT_PORT)
        self.client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)
        self.client.loop_start()

    def stop(self) -> None:
        self._stop = True
        try:
            self.client.loop_stop()
        finally:
            self.client.disconnect()
            self.http.close()

    def on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            logger.error("MQTT connect failed rc=%s", rc)
            return
        logger.info("Connected to MQTT broker, subscribing to %s", MQTT_TOPIC)
        client.subscribe(MQTT_TOPIC, qos=0)

    def on_disconnect(self, client, userdata, rc):
        if self._stop:
            logger.info("MQTT disconnected")
            return
        logger.warning("Unexpected MQTT disconnect rc=%s", rc)

    def on_message(self, client, userdata, msg):
        try:
            self.handle_message(msg.topic, msg.payload)
        except Exception as exc:
            logger.exception("Failed handling message from topic %s: %s", msg.topic, exc)

    def handle_message(self, topic: str, payload_bytes: bytes) -> None:
        topic_meta = parse_hfp_topic(topic)

        if topic_meta["transport_mode"] != "metro":
            return
        if topic_meta["event_type"] != "vp":
            return

        payload = json.loads(payload_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            logger.warning("Skipping non-dict payload on %s", topic)
            return

        vp = payload.get("VP")
        if not isinstance(vp, dict):
            logger.warning("Skipping payload without VP object on %s", topic)
            return

        oper_json = vp.get("oper")
        veh_json = vp.get("veh")

        if oper_json is not None and str(oper_json).zfill(4) != topic_meta["oper"]:
            logger.warning(
                "Operator mismatch topic_oper=%s payload_oper=%s topic=%s",
                topic_meta["oper"], oper_json, topic
            )

        if veh_json is not None and str(veh_json).zfill(5) != topic_meta["veh"]:
            logger.warning(
                "Vehicle mismatch topic_veh=%s payload_veh=%s topic=%s",
                topic_meta["veh"], veh_json, topic
            )

        now_iso = utcnow_iso()
        event_ts_us = parse_event_ts_to_us(vp)

        mqtt_base_topic = (
            f"/{topic_meta['prefix']}/{topic_meta['version']}/{topic_meta['journey_type']}/"
            f"{topic_meta['temporal_type']}/{topic_meta['event_type']}/{topic_meta['transport_mode']}/"
            f"{topic_meta['oper']}/{topic_meta['veh']}"
        )

        batch_payload: List[Dict[str, Any]] = []

        for json_path, value in flatten_json(vp):
            field_name = json_path.split(".")[-1]

            if field_name in SKIP_KEYS:
                continue

            if value is None and not POST_NULL_VALUES:
                continue

            tag_path = build_tag_path_from_topic(topic_meta, field_name)

            learned = self.registry.upsert_new_if_missing(
                tag_path=tag_path,
                json_field=field_name,
                json_path=f"VP.{json_path}",
                mqtt_base_topic=mqtt_base_topic,
                oper=topic_meta["oper"],
                veh=topic_meta["veh"],
                transport_mode=topic_meta["transport_mode"],
                now_iso=now_iso,
                collector_id=COLLECTOR_ID,
            )

            outbound_identity = resolve_outbound_identity(
                identity_mode=IDENTITY_MODE,
                learned_uuid=learned.uuid,
                topic_meta=topic_meta,
                field_name=field_name,
            )

            batch_payload.append(
                {
                    "uuid": outbound_identity,
                    "ts": event_ts_us,
                    "value": value,
                }
            )

        if batch_payload:
            post_batch(self.http, batch_payload)


# ============================================================================
# Main
# ============================================================================

def main() -> int:
    collector = HfpMetroCollector()

    def _handle_signal(signum, frame):
        logger.info("Received signal %s, shutting down", signum)
        collector.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    collector.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        collector.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())