import pandas as pd
import streamlit as st
from ui_helpers import fmt_dt_us


def render_events(safe_get):
    with st.expander("Recent events", expanded=False):
        ev = safe_get("/events/recent", params={"n": 100})
        if ev and "events" in ev:
            events = pd.DataFrame(ev["events"])
            if not events.empty:
                if "ts" in events.columns:
                    events["ts_text"] = events["ts"].apply(fmt_dt_us)

                left, right = st.columns(2)

                with left:
                    st.caption("Recent anomalies")
                    anoms = events[events["kind"] == "anomaly"].copy() if "kind" in events.columns else pd.DataFrame()
                    if not anoms.empty:
                        cols = [
                            c for c in [
                                "ts_text",
                                "uuid",
                                "vtype",
                                "model",
                                "value",
                                "prediction",
                                "residual",
                                "score",
                                "threshold",
                                "reason",
                            ]
                            if c in anoms.columns
                        ]
                        st.dataframe(anoms[cols].head(30), width="stretch", hide_index=True)
                    else:
                        st.info("No recent anomaly events")

                with right:
                    st.caption("Recent service / lifecycle events")
                    if "kind" in events.columns:
                        keep_kinds = [
                            "uuid_discovered",
                            "runtime_state_created",
                            "model_assigned",
                            "scoring_state_changed",
                            "learned_tag_cap_reached",
                            "worker_crash",
                            "degraded",
                            "error",
                            "config_saved",
                            "config_applied",
                            "config_apply_failed",
                        ]
                        other = events[events["kind"].isin(keep_kinds)].copy()
                    else:
                        other = pd.DataFrame()

                    if not other.empty:
                        cols = [c for c in [
                            "ts_text", "kind", "uuid", "vtype", "event",
                            "assigned_model", "enabled", "error", "err", "source"
                        ] if c in other.columns]
                        st.dataframe(other[cols].head(30), width="stretch")
                    else:
                        st.info("No recent non-anomaly events")
        else:
            st.warning("Cannot read /events/recent")