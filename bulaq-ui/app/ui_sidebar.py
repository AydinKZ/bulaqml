import pandas as pd
import streamlit as st


def render_sidebar(cfg, stats, runtime_hist, safe_get, base_url):
    with st.sidebar:
        with st.expander("Console controls", expanded=True):
            st.checkbox("Auto refresh", key="autorefresh")
            st.selectbox("Refresh (sec)", [2, 5, 10, 15], key="refresh_sec")
            st.caption(f"Backend: {base_url}")
            st.caption(f"Config ID: {cfg.get('cfg_id', '-')}")

        with st.expander("Fleet summary", expanded=False):
            res_sidebar = safe_get("/debug/resources") or {}

            lifecycle_rows = [
                {"metric": "Learned UUIDs", "value": stats.get("learned_uuid_count", stats.get("uuid_count", 0))},
                {"metric": "Discovered", "value": stats.get("learned_discovered", 0)},
                {"metric": "Assigned", "value": stats.get("learned_assigned", 0)},
                {"metric": "Active", "value": stats.get("learned_active", 0)},
                {"metric": "Disabled", "value": stats.get("learned_disabled", 0)},
            ]
            runtime_rows = [
                {"group": "Runtime", "metric": "Runtime UUIDs", "value": stats.get("runtime_uuid_count", stats.get("uuid_count", 0))},
                {"group": "Runtime", "metric": "Runtime models", "value": stats.get("runtime_models", stats.get("models", 0))},
                {"group": "Runtime", "metric": "Runtime numeric", "value": stats.get("runtime_numeric_models", stats.get("numeric_models", 0))},
                {"group": "Runtime", "metric": "Runtime bool", "value": stats.get("runtime_bool_models", stats.get("bool_models", 0))},
                {"group": "Runtime", "metric": "Runtime cat", "value": stats.get("runtime_cat_models", stats.get("cat_models", 0))},
                {"group": "Runtime", "metric": "Snapshots", "value": stats.get("snapshots", 0)},
                {"group": "Service", "metric": "Queue depth", "value": res_sidebar.get("queue_depth", "-")},
                {"group": "Service", "metric": "Workers alive", "value": res_sidebar.get("workers_alive", "-")},
                {"group": "Service", "metric": "Worker restarts", "value": res_sidebar.get("worker_restarts", "-")},
                {"group": "Service", "metric": "RSS MiB", "value": res_sidebar.get("rss_mib", "-")},
                {"group": "Service", "metric": "CPU %", "value": res_sidebar.get("cpu_percent", "-")},
            ]

            st.caption("Lifecycle")
            st.dataframe(pd.DataFrame(lifecycle_rows), width="stretch", height=210, hide_index=True)

            st.caption("Runtime / service")
            st.dataframe(pd.DataFrame(runtime_rows), width="stretch", height=300, hide_index=True)

        with st.expander("Runtime trends", expanded=False):
            hist_sidebar = pd.DataFrame(runtime_hist)
            if not hist_sidebar.empty:
                hist_sidebar = hist_sidebar.sort_values("ts").set_index("ts")

                r2c1, r1c2 = st.columns(2)
                r1c1, r2c2 = st.columns(2)

                with r1c1:
                    st.caption("Queue")
                    if "queue_depth" in hist_sidebar.columns:
                        st.line_chart(hist_sidebar[["queue_depth"]], height=120)

                with r1c2:
                    st.caption("RSS Mem (MB)")
                    if "rss_mib" in hist_sidebar.columns:
                        st.line_chart(hist_sidebar[["rss_mib"]], height=120)

                with r2c1:
                    st.caption("CPU")
                    if "cpu_percent" in hist_sidebar.columns:
                        st.line_chart(hist_sidebar[["cpu_percent"]], height=120)

                with r2c2:
                    trend_cols = [c for c in ["runtime_models", "runtime_uuid_count"] if c in hist_sidebar.columns]
                    st.caption("Runtime")
                    if trend_cols:
                        st.line_chart(hist_sidebar[trend_cols], height=120)
            else:
                st.info("Waiting for runtime samples...")