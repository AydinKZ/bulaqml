import time
import pandas as pd
import streamlit as st

from ui_api import BASE, api_get, safe_get, safe_post
from ui_state import init_session_state
from ui_sidebar import render_sidebar
from ui_explorer import render_explorer
from ui_workspace import render_workspace
from ui_events import render_events


st.set_page_config(page_title="Bulaq ML Console", layout="wide")
st.title("Bulaq ML — Time Series Anomaly Detection")

init_session_state()

try:
    cfg = api_get("/config")
    stats = api_get("/stats")
except Exception as e:
    st.error(f"Scorer not reachable at {BASE}: {e}")
    st.stop()

now = time.time()
if now - st.session_state.last_runtime_pull >= 10:
    res = safe_get("/debug/resources")
    stat2 = safe_get("/stats")
    if res and stat2:
        st.session_state.runtime_hist.append(
            {
                "ts": pd.Timestamp.utcnow(),
                "queue_depth": res.get("queue_depth"),
                "rss_mib": res.get("rss_mib"),
                "cpu_percent": res.get("cpu_percent"),
                "runtime_models": stat2.get("runtime_models", stat2.get("models")),
                "runtime_uuid_count": stat2.get("runtime_uuid_count", stat2.get("uuid_count")),
                "learned_uuid_count": stat2.get("learned_uuid_count", stat2.get("uuid_count")),
                "workers_alive": res.get("workers_alive"),
                "worker_restarts": res.get("worker_restarts"),
            }
        )
        st.session_state.runtime_hist = st.session_state.runtime_hist[-100:]
        st.session_state.last_runtime_pull = now

render_sidebar(cfg=cfg, stats=stats, runtime_hist=st.session_state.runtime_hist, safe_get=safe_get, base_url=BASE)
uuid = render_explorer(safe_get=safe_get)
render_workspace(uuid=uuid, cfg=cfg, safe_get=safe_get, safe_post=safe_post)
render_events(safe_get=safe_get)

if st.session_state.autorefresh:
    time.sleep(st.session_state.refresh_sec)
    st.rerun()