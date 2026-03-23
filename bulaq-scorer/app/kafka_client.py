import json
import logging
from confluent_kafka import Producer


class KafkaClient:
    def __init__(self, settings):
        self.settings = settings
        self.producer = None

    def init(self):
        if not self.settings.kafka_enabled or not self.settings.kafka_bootstrap_servers:
            return

        try:
            cfg = {
                "bootstrap.servers": self.settings.kafka_bootstrap_servers,
                "client.id": self.settings.kafka_client_id,
                "security.protocol": self.settings.kafka_security_protocol,
            }

            if self.settings.kafka_security_protocol.upper().startswith("SASL"):
                cfg["sasl.mechanism"] = self.settings.kafka_sasl_mechanism
                cfg["sasl.username"] = self.settings.kafka_username
                cfg["sasl.password"] = self.settings.kafka_password

            self.producer = Producer(cfg)
        except Exception as e:
            self.producer = None
            logging.getLogger("bulaq-scorer").warning("Kafka forwarding disabled: %r", e)

    def emit(self, event: dict):
        if self.producer is None:
            return

        try:
            kind = event.get("kind", "")
            topic = self.settings.kafka_config_topic if kind.startswith("config_") else self.settings.kafka_events_topic
            key = event.get("uuid") or event.get("config_name") or kind or "event"

            self.producer.produce(
                topic=topic,
                key=str(key).encode("utf-8"),
                value=json.dumps(event, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
            )
            self.producer.poll(0)
        except Exception:
            pass

    def close(self):
        try:
            if self.producer is not None:
                self.producer.flush(2.0)
        except Exception:
            pass