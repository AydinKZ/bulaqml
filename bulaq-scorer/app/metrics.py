import psutil
from prometheus_client import Counter, Gauge, Histogram

PROC = psutil.Process()

ingest_events = Counter("bulaq_ingest_total", "Events accepted")
ingest_dropped = Counter("bulaq_ingest_dropped_total", "Events dropped")
score_events = Counter("bulaq_score_total", "Events scored")
score_anomalies = Counter("bulaq_anomalies_total", "Anomalies detected")

queue_depth = Gauge("bulaq_queue_depth", "Queue size")
models_total = Gauge("bulaq_models_total", "Active models")

rss_bytes = Gauge("bulaq_rss_bytes", "RSS bytes")
cpu_percent = Gauge("bulaq_cpu_percent", "CPU usage")

ingest_latency = Histogram("bulaq_ingest_latency_seconds", "HTTP ingest latency")
score_latency = Histogram("bulaq_score_latency_seconds", "Scoring latency")

def update_resource_metrics():
    rss_bytes.set(PROC.memory_info().rss)
    cpu_percent.set(PROC.cpu_percent(interval=None))