import time


SYSLOG_EVENT_KINDS = {
    "new_uuid",
    "anomaly",
    "worker_crash",
    "degraded",
    "error",
    "config_saved",
    "config_applied",
    "config_apply_failed",
    "uuid_registry_updated",
}


class EventBus:
    def __init__(self, events_deque, syslog_client, kafka_client, cfg_id_getter):
        self.events = events_deque
        self.syslog_client = syslog_client
        self.kafka_client = kafka_client
        self.cfg_id_getter = cfg_id_getter

    def emit(self, kind: str, event: dict):
        evt = {
            "ts": int(time.time() * 1e6),
            "kind": kind,
            "cfg_id": self.cfg_id_getter(),
            **event,
        }
        self.events.appendleft(evt)

        if kind in SYSLOG_EVENT_KINDS:
            self.syslog_client.emit(evt)

        self.kafka_client.emit(evt)