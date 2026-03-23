import json
import logging
import socket
from logging.handlers import SysLogHandler


class SyslogClient:
    def __init__(self, settings):
        self.settings = settings
        self.logger = logging.getLogger("bulaq.syslog")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.ready = False

    def init(self):
        if not self.settings.syslog_enabled:
            return

        if self.logger.handlers:
            self.ready = True
            return

        try:
            facility = getattr(
                SysLogHandler,
                f"LOG_{self.settings.syslog_facility.upper()}",
                SysLogHandler.LOG_LOCAL0,
            )
            socktype = socket.SOCK_STREAM if self.settings.syslog_proto.lower() == "tcp" else socket.SOCK_DGRAM

            handler = SysLogHandler(
                address=(self.settings.syslog_host, self.settings.syslog_port),
                facility=facility,
                socktype=socktype,
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(handler)
            self.ready = True
        except Exception as e:
            self.ready = False
            logging.getLogger("bulaq-scorer").warning("Syslog disabled (init failed): %r", e)

    def emit(self, event: dict):
        if not (self.settings.syslog_enabled and self.ready):
            return
        try:
            payload = {"app": self.settings.syslog_tag, **event}
            self.logger.info(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
        except Exception:
            pass