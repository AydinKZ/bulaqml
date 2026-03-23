from pydantic import BaseModel, ConfigDict
import os

class Settings(BaseModel):
    model_config = ConfigDict(protected_namespaces=())  # avoid "model_" namespace warnings

    # ingest/runtime
    queue_max: int = int(os.getenv("QUEUE_MAX", "50000"))
    max_body_bytes: int = int(os.getenv("MAX_BODY_BYTES", str(2 * 1024 * 1024)))
    batch_max_items: int = int(os.getenv("BATCH_MAX_ITEMS", "500"))
    workers: int = int(os.getenv("SCORER_WORKERS", "2"))

    # model store (renamed from mdl_ in response mapping)
    mdl_max_keys: int = int(os.getenv("MODEL_MAX_KEYS", "5000"))
    mdl_ttl_sec: int = int(os.getenv("MODEL_TTL_SEC", "21600"))
    evict_every_sec: int = int(os.getenv("EVICT_EVERY_SEC", "30"))

    # optional snapshots (if you keep old UI snapshot tab)
    enable_snapshots: bool = os.getenv("ENABLE_SNAPSHOTS", "0") == "1"
    snapshot_points: int = int(os.getenv("SNAPSHOT_POINTS", "50"))

    # detector
    detector: str = os.getenv("DETECTOR", "hst")  # hst | xstream | robust_z (if you implement)
    n_trees: int = int(os.getenv("N_TREES", "15"))
    height: int = int(os.getenv("HEIGHT", "12"))
    window_size: int = int(os.getenv("WINDOW_SIZE", "200"))

    # thresholding
    threshold_method: str = os.getenv("THRESHOLD_METHOD", "quantile")  # quantile | static (mad later if you add)
    threshold_q: float = float(os.getenv("THRESHOLD_Q", "0.995"))
    static_threshold: float = float(os.getenv("STATIC_THRESHOLD", "0.8"))

    # alert logic
    cooldown_sec: int = int(os.getenv("COOLDOWN_SEC", "30"))
    k_of_n_k: int = int(os.getenv("K_OF_N_K", "1"))
    k_of_n_n: int = int(os.getenv("K_OF_N_N", "1"))

    # bool/cat knobs (UI expects them; even if scorer ignores for now)
    bool_flip_window: int = int(os.getenv("BOOL_FLIP_WINDOW", "100"))
    bool_flip_rate_hi: float = float(os.getenv("BOOL_FLIP_RATE_HI", "0.2"))

    cat_decay: float = float(os.getenv("CAT_DECAY", "0.999"))
    cat_novelty_min_prob: float = float(os.getenv("CAT_NOVELTY_MIN_PROB", "0.01"))
    # shared numeric stability
    prob_eps: float = float(os.getenv("PROB_EPS", "1e-9"))

    # bool thresholding (use same default as numeric if not set)
    bool_threshold_q: float = float(os.getenv("BOOL_THRESHOLD_Q", str(float(os.getenv("THRESHOLD_Q", "0.995")))))
    bool_alpha: float = float(os.getenv("BOOL_ALPHA", "0.02"))
    bool_stuck_sec: int = int(os.getenv("BOOL_STUCK_SEC", "0"))  # 0 disables stuck detection

    # cat thresholding
    cat_threshold_q: float = float(os.getenv("CAT_THRESHOLD_Q", str(float(os.getenv("THRESHOLD_Q", "0.995")))))
    cat_smoothing_alpha: float = float(os.getenv("CAT_SMOOTHING_ALPHA", "1.0"))
    cat_transition_enable: bool = os.getenv("CAT_TRANSITION_ENABLE", "1") == "1"
    cat_transition_weight: float = float(os.getenv("CAT_TRANSITION_WEIGHT", "1.0"))
    cat_new_category_is_anom: bool = os.getenv("CAT_NEW_CATEGORY_IS_ANOM", "1") == "1"

    enable_snapshots: bool = os.getenv("ENABLE_SNAPSHOTS", "1") == "1"
    snapshot_points: int = int(os.getenv("SNAPSHOT_POINTS", "500"))
    # postgres config registry
    pg_dsn: str = os.getenv("PG_DSN", "")

    # kafka event forwarding
    kafka_enabled: bool = os.getenv("KAFKA_ENABLED", "0") == "1"
    kafka_bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
    kafka_security_protocol: str = os.getenv("KAFKA_P_SECURITY_PROTOCOL", "PLAINTEXT")
    kafka_sasl_mechanism: str = os.getenv("KAFKA_P_SASL_MECHANISM", "")
    kafka_username: str = os.getenv("KAFKA_P_USERNAME", "")
    kafka_password: str = os.getenv("KAFKA_P_PASSWORD", "")
    kafka_client_id: str = os.getenv("KAFKA_CLIENT_ID", "bulaq-scorer")

    kafka_events_topic: str = os.getenv("KAFKA_EVENTS_TOPIC", "bulaq-events")
    kafka_config_topic: str = os.getenv("KAFKA_CONFIG_TOPIC", "bulaq-config-events")

    syslog_enabled: bool = os.getenv("SYSLOG_ENABLED", "0") == "1"
    syslog_host: str = os.getenv("SYSLOG_HOST", "localhost")
    syslog_port: int = int(os.getenv("SYSLOG_PORT", "514"))
    syslog_proto: str = os.getenv("SYSLOG_PROTO", "udp")
    syslog_facility: str = os.getenv("SYSLOG_FACILITY", "local0")
    syslog_tag: str = os.getenv("SYSLOG_TAG", "bulaq-scorer")


    # learned tags / assignment gating
    learned_tags_enabled: bool = os.getenv("LEARNED_TAGS_ENABLED", "1") == "1"
    learned_tags_max: int = int(os.getenv("LEARNED_TAGS_MAX", "1000"))
    enable_assignment_gate: bool = os.getenv("ENABLE_ASSIGNMENT_GATE", "1") == "1"
    assignment_cache_ttl_sec: int = int(os.getenv("ASSIGNMENT_CACHE_TTL_SEC", "60"))

    # ewma numeric defaults
    ewma_alpha: float = float(os.getenv("EWMA_ALPHA", "0.05"))
    ewma_residual_threshold_q: float = float(
        os.getenv("EWMA_RESIDUAL_THRESHOLD_Q", str(float(os.getenv("THRESHOLD_Q", "0.995"))))
    )
    ewma_warmup_min: int = int(os.getenv("EWMA_WARMUP_MIN", "30"))
    ewma_min_scale: float = float(os.getenv("EWMA_MIN_SCALE", "1e-6"))