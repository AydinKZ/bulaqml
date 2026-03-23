import altair as alt
import pandas as pd
import streamlit as st

from ui_ai import AI_API_KEY, run_ai_analysis_for_uuid
from ui_helpers import (
    allowed_models_for_vtype,
    compact_json,
    cfg_default,
    default_model_for_vtype,
    extract_existing_params,
    make_assignment_payload,
    parse_float,
    status_badge,
)


def load_uuid_context(uuid: str, safe_get):
    selected_tag = None
    detail = None
    snap = None
    history_resp = None
    recent_events_resp = None
    snapshot_rows = []

    if uuid:
        selected_tag_resp = safe_get(f"/learned-tags/{uuid}")
        selected_tag = selected_tag_resp.get("item") if selected_tag_resp and selected_tag_resp.get("ok") else None
        detail = safe_get("/uuid/summary", params={"uuid": uuid})
        history_resp = safe_get(f"/learned-tags/{uuid}/model-history", params={"limit": 20})
        recent_events_resp = safe_get("/events/recent", params={"n": 200})

        snap_vtype = "all"
        if selected_tag and selected_tag.get("vtype") in ("numeric", "bool", "cat"):
            snap_vtype = selected_tag["vtype"]

        snap = safe_get("/snapshot", params={"uuid": uuid, "vtype": snap_vtype, "n": 500})
        snapshot_rows = snap.get("rows", []) if snap else []

    return selected_tag, detail, snap, history_resp, recent_events_resp, snapshot_rows


def render_workspace(uuid, cfg, safe_get, safe_post):
    selected_tag, detail, snap, history_resp, recent_events_resp, snapshot_rows = load_uuid_context(uuid, safe_get)

    with st.expander("Selected Tag workspace", expanded=True):
        if not uuid:
            st.info("Select a UUID to start working.")
            return

        if not selected_tag:
            st.warning("Selected UUID could not be loaded from backend.")
            return

        st.markdown(f"### Tag UUID: `{uuid}`")

        top_a, top_b, top_c, top_d, top_e, top_f = st.columns([2, 1, 2, 1, 1, 1])
        with top_a:
            st.caption("Lifecycle")
            st.write(status_badge(selected_tag.get("status")))
        with top_b:
            st.caption("VType")
            st.write(selected_tag.get("vtype", "-"))
        with top_c:
            st.caption("Assigned model")
            st.write(selected_tag.get("assigned_model") or "-")
        with top_d:
            st.caption("Enabled")
            st.write("yes" if bool(selected_tag.get("enabled_for_scoring")) else "no")
        with top_e:
            st.caption("Runtime")
            st.write("loaded" if bool(selected_tag.get("runtime_loaded")) else "not loaded")
        with top_f:
            st.caption("Recent anomalies")
            st.write(detail.get("recent_anomaly_count", 0))

        left, right = st.columns([3, 2])

        if detail:
            m7, m9, m10 = st.columns(3)
            m7.metric("Last seen", detail.get("last_seen_text", "-"))
            m9.metric("Current threshold", detail.get("current_threshold", "-"))
            m10.metric("Current score", detail.get("current_score", "-"))

            if detail.get("last_prediction") is not None or detail.get("last_residual") is not None:
                mp1, mp2 = st.columns(2)
                mp1.metric("Last prediction", detail.get("last_prediction"))
                mp2.metric("Last residual", detail.get("last_residual"))


        with st.expander("Current assigned settings", expanded=False):
            st.write(
                {
                    "uuid": selected_tag.get("uuid"),
                    "vtype": selected_tag.get("vtype"),
                    "status": selected_tag.get("status"),
                    "assigned_model": selected_tag.get("assigned_model"),
                    "enabled_for_scoring": selected_tag.get("enabled_for_scoring"),
                }
            )
            st.json(selected_tag.get("model_settings_json") or {})


        with st.expander("Model assignment history", expanded=False):
            hist_items = history_resp.get("items", []) if history_resp else []
            if hist_items:
                hist_df = pd.DataFrame(hist_items).copy()
                if "assigned_at" in hist_df.columns:
                    hist_df["assigned_at"] = pd.to_datetime(hist_df["assigned_at"], errors="coerce")
                if "model_settings_json" in hist_df.columns:
                    hist_df["model_settings_json"] = hist_df["model_settings_json"].apply(compact_json)

                show_cols = [c for c in [
                    "assigned_at",
                    "assigned_model",
                    "actor",
                    "source",
                    "model_settings_json",
                ] if c in hist_df.columns]
                st.dataframe(hist_df[show_cols], width="stretch", height=220, hide_index=True)
            else:
                st.info("No assignment history yet.")

        with st.expander("Assignment and scoring controls", expanded=True):
            vtype = selected_tag.get("vtype")
            assigned_model_current = selected_tag.get("assigned_model") or default_model_for_vtype(vtype)
            existing_params = extract_existing_params(selected_tag)
            tag_status = selected_tag.get("status")
            if tag_status == "discovered":
                st.info("This UUID is discovered but not assigned. Save an assignment before enabling scoring.")
            elif tag_status == "assigned":
                st.info("This UUID has an assigned model, but scoring is not active. Enable scoring when ready.")
            elif tag_status == "disabled":
                st.warning("This UUID is assigned but currently disabled for scoring.")
            elif tag_status == "active":
                st.success("This UUID is actively scored.")
            ctrl_left, ctrl_right = st.columns([3, 2])

            with ctrl_left:
                model_options = allowed_models_for_vtype(vtype)
                chosen_model = st.selectbox(
                    "Assigned model",
                    model_options,
                    index=model_options.index(assigned_model_current) if assigned_model_current in model_options else 0,
                    key=f"model_select_{uuid}",
                ) if model_options else ""

                assignment_error = None
                assignment_payload = None

                try:
                    if vtype == "numeric":
                        if chosen_model == "half_space_trees":
                            n_trees = st.number_input(
                                "n_trees",
                                min_value=1,
                                value=int(existing_params.get("n_trees", cfg_default(cfg, "numeric", "half_space_trees", "n_trees", fallback=15))),
                                step=1,
                                key=f"n_trees_{uuid}",
                            )
                            height = st.number_input(
                                "height",
                                min_value=1,
                                value=int(existing_params.get("height", cfg_default(cfg, "numeric", "half_space_trees", "height", fallback=12))),
                                step=1,
                                key=f"height_{uuid}",
                            )
                            window_size = st.number_input(
                                "window_size",
                                min_value=1,
                                value=int(existing_params.get("window_size", cfg_default(cfg, "numeric", "half_space_trees", "window_size", fallback=200))),
                                step=1,
                                key=f"window_size_{uuid}",
                            )
                            threshold_q_raw = st.text_input(
                                "threshold_q",
                                value=str(existing_params.get("threshold_q", cfg_default(cfg, "numeric", "half_space_trees", "threshold_q", fallback=0.995))),
                                key=f"threshold_q_{uuid}",
                            )
                            warmup_min = st.number_input(
                                "warmup_min",
                                min_value=0,
                                value=int(
                                    existing_params.get(
                                        "warmup_min",
                                        cfg_default(cfg, "numeric", "half_space_trees", "warmup_min", fallback=200),
                                    )
                                ),
                                step=1,
                                key=f"warmup_min_hst_{uuid}",
                            )
                            assignment_payload = make_assignment_payload(
                                vtype=vtype,
                                model_name=chosen_model,
                                form_values={
                                    "n_trees": int(n_trees),
                                    "height": int(height),
                                    "window_size": int(window_size),
                                    "threshold_q": parse_float(threshold_q_raw, "threshold_q"),
                                    "warmup_min": int(warmup_min),
                                },
                            )

                        elif chosen_model == "ewma_residual":
                            alpha_raw = st.text_input(
                                "alpha",
                                value=str(existing_params.get("alpha", cfg_default(cfg, "numeric", "ewma_residual", "alpha", fallback=0.05))),
                                key=f"alpha_{uuid}",
                            )
                            residual_threshold_q_raw = st.text_input(
                                "residual_threshold_q",
                                value=str(
                                    existing_params.get(
                                        "residual_threshold_q",
                                        cfg_default(cfg, "numeric", "ewma_residual", "residual_threshold_q", fallback=0.995),
                                    )
                                ),
                                key=f"residual_threshold_q_{uuid}",
                            )
                            warmup_min = st.number_input(
                                "warmup_min",
                                min_value=0,
                                value=int(existing_params.get("warmup_min", cfg_default(cfg, "numeric", "ewma_residual", "warmup_min", fallback=30))),
                                step=1,
                                key=f"warmup_min_ewma_{uuid}",
                            )
                            min_scale_raw = st.text_input(
                                "min_scale",
                                value=str(existing_params.get("min_scale", cfg_default(cfg, "numeric", "ewma_residual", "min_scale", fallback=1e-6))),
                                key=f"min_scale_{uuid}",
                            )
                            assignment_payload = make_assignment_payload(
                                vtype=vtype,
                                model_name=chosen_model,
                                form_values={
                                    "alpha": parse_float(alpha_raw, "alpha"),
                                    "residual_threshold_q": parse_float(residual_threshold_q_raw, "residual_threshold_q"),
                                    "warmup_min": int(warmup_min),
                                    "min_scale": parse_float(min_scale_raw, "min_scale"),
                                },
                            )

                    elif vtype == "bool":
                        bool_threshold_q_raw = st.text_input(
                            "bool_threshold_q",
                            value=str(
                                existing_params.get(
                                    "bool_threshold_q",
                                    cfg_default(cfg, "bool", "bernoulli_surprisal", "bool_threshold_q", fallback=0.995),
                                )
                            ),
                            key=f"bool_threshold_q_{uuid}",
                        )
                        bool_alpha_raw = st.text_input(
                            "bool_alpha",
                            value=str(existing_params.get("bool_alpha", cfg_default(cfg, "bool", "bernoulli_surprisal", "bool_alpha", fallback=0.02))),
                            key=f"bool_alpha_{uuid}",
                        )
                        bool_flip_rate_hi_raw = st.text_input(
                            "bool_flip_rate_hi",
                            value=str(
                                existing_params.get(
                                    "bool_flip_rate_hi",
                                    cfg_default(cfg, "bool", "bernoulli_surprisal", "bool_flip_rate_hi", fallback=0.2),
                                )
                            ),
                            key=f"bool_flip_rate_hi_{uuid}",
                        )
                        bool_stuck_sec = st.number_input(
                            "bool_stuck_sec",
                            min_value=0,
                            value=int(existing_params.get("bool_stuck_sec", cfg_default(cfg, "bool", "bernoulli_surprisal", "bool_stuck_sec", fallback=0))),
                            step=1,
                            key=f"bool_stuck_sec_{uuid}",
                        )
                        assignment_payload = make_assignment_payload(
                            vtype=vtype,
                            model_name=chosen_model,
                            form_values={
                                "bool_threshold_q": parse_float(bool_threshold_q_raw, "bool_threshold_q"),
                                "bool_alpha": parse_float(bool_alpha_raw, "bool_alpha"),
                                "bool_flip_rate_hi": parse_float(bool_flip_rate_hi_raw, "bool_flip_rate_hi"),
                                "bool_stuck_sec": int(bool_stuck_sec),
                            },
                        )

                    elif vtype == "cat":
                        cat_threshold_q_raw = st.text_input(
                            "cat_threshold_q",
                            value=str(
                                existing_params.get(
                                    "cat_threshold_q",
                                    cfg_default(cfg, "cat", "categorical_surprisal", "cat_threshold_q", fallback=0.995),
                                )
                            ),
                            key=f"cat_threshold_q_{uuid}",
                        )
                        cat_decay_raw = st.text_input(
                            "cat_decay",
                            value=str(existing_params.get("cat_decay", cfg_default(cfg, "cat", "categorical_surprisal", "cat_decay", fallback=0.999))),
                            key=f"cat_decay_{uuid}",
                        )
                        cat_smoothing_alpha_raw = st.text_input(
                            "cat_smoothing_alpha",
                            value=str(
                                existing_params.get(
                                    "cat_smoothing_alpha",
                                    cfg_default(cfg, "cat", "categorical_surprisal", "cat_smoothing_alpha", fallback=1.0),
                                )
                            ),
                            key=f"cat_smoothing_alpha_{uuid}",
                        )
                        cat_transition_enable = st.checkbox(
                            "cat_transition_enable",
                            value=bool(
                                existing_params.get(
                                    "cat_transition_enable",
                                    cfg_default(cfg, "cat", "categorical_surprisal", "cat_transition_enable", fallback=True),
                                )
                            ),
                            key=f"cat_transition_enable_{uuid}",
                        )
                        cat_transition_weight_raw = st.text_input(
                            "cat_transition_weight",
                            value=str(
                                existing_params.get(
                                    "cat_transition_weight",
                                    cfg_default(cfg, "cat", "categorical_surprisal", "cat_transition_weight", fallback=1.0),
                                )
                            ),
                            key=f"cat_transition_weight_{uuid}",
                        )
                        cat_novelty_min_prob_raw = st.text_input(
                            "cat_novelty_min_prob",
                            value=str(
                                existing_params.get(
                                    "cat_novelty_min_prob",
                                    cfg_default(cfg, "cat", "categorical_surprisal", "cat_novelty_min_prob", fallback=0.01),
                                )
                            ),
                            key=f"cat_novelty_min_prob_{uuid}",
                        )
                        cat_new_category_is_anom = st.checkbox(
                            "cat_new_category_is_anom",
                            value=bool(
                                existing_params.get(
                                    "cat_new_category_is_anom",
                                    cfg_default(cfg, "cat", "categorical_surprisal", "cat_new_category_is_anom", fallback=True),
                                )
                            ),
                            key=f"cat_new_category_is_anom_{uuid}",
                        )
                        assignment_payload = make_assignment_payload(
                            vtype=vtype,
                            model_name=chosen_model,
                            form_values={
                                "cat_threshold_q": parse_float(cat_threshold_q_raw, "cat_threshold_q"),
                                "cat_decay": parse_float(cat_decay_raw, "cat_decay"),
                                "cat_smoothing_alpha": parse_float(cat_smoothing_alpha_raw, "cat_smoothing_alpha"),
                                "cat_transition_enable": bool(cat_transition_enable),
                                "cat_transition_weight": parse_float(cat_transition_weight_raw, "cat_transition_weight"),
                                "cat_novelty_min_prob": parse_float(cat_novelty_min_prob_raw, "cat_novelty_min_prob"),
                                "cat_new_category_is_anom": bool(cat_new_category_is_anom),
                            },
                        )
                except Exception as e:
                    assignment_error = str(e)

                if assignment_error:
                    st.error(assignment_error)
                else:
                    st.caption("Assignment settings parsed successfully.")

            with ctrl_right:
                st.markdown("##### Actions")

                action_row1 = st.columns(2)
                action_row2 = st.columns(1)

                with action_row1[0]:
                    assign_clicked = st.button("Save assignment", type="primary", width="stretch", key=f"assign_btn_{uuid}")
                with action_row1[1]:
                    enable_clicked = st.button("Enable scoring", width="stretch", key=f"enable_btn_{uuid}")
                with action_row2[0]:
                    disable_clicked = st.button("Disable scoring", width="stretch", key=f"disable_btn_{uuid}")

                if assign_clicked and assignment_payload:
                    with st.spinner("Applying assignment..."):
                        out = safe_post(f"/learned-tags/{uuid}/assign", assignment_payload)
                    if out.get("ok"):
                        st.success("Assignment saved.")
                        st.rerun()
                    else:
                        st.error(out.get("error", "Failed to save assignment"))

                if enable_clicked:
                    with st.spinner("Enabling scoring..."):
                        out = safe_post(
                            f"/learned-tags/{uuid}/enable",
                            {
                                "enabled": True,
                                "actor": "ui",
                                "source": "ui",
                                "reset_runtime_state": True,
                            },
                        )
                    if out.get("ok"):
                        st.success("Scoring enabled.")
                        st.rerun()
                    else:
                        st.error(out.get("error", "Failed to enable scoring"))

                if disable_clicked:
                    with st.spinner("Disabling scoring..."):
                        out = safe_post(
                            f"/learned-tags/{uuid}/enable",
                            {
                                "enabled": False,
                                "actor": "ui",
                                "source": "ui",
                                "reset_runtime_state": True,
                            },
                        )
                    if out.get("ok"):
                        st.success("Scoring disabled.")
                        st.rerun()
                    else:
                        st.error(out.get("error", "Failed to disable scoring"))

                st.caption("Assignment and scoring are separate actions. Use Save assignment first, then Enable scoring.")



    if uuid and snap and snap.get("rows"):
        with st.expander("UUID charts and recent rows", expanded=True):
            df = pd.DataFrame(snap["rows"])
            df["ts"] = pd.to_datetime(df["ts"], unit="us", errors="coerce")
            df = df.sort_values("ts")

            if not df.empty:
                chart_vtype = selected_tag.get("vtype") if selected_tag else "all"

                tab_names = ["Value", "Score", "Rows"]
                if chart_vtype == "numeric" and "prediction" in df.columns and df["prediction"].notna().any():
                    tab_names = ["Value", "Score", "Prediction", "Rows"]
                elif chart_vtype == "cat":
                    tab_names = ["Activity", "Score", "Rows"]

                tabs = st.tabs(tab_names)

                with tabs[0]:
                    if chart_vtype in ("numeric", "bool"):
                        plot_col = "plot_value" if "plot_value" in df.columns else "value"
                        base = alt.Chart(df).encode(x=alt.X("ts:T", title="Time"))
                        line = base.mark_line().encode(y=alt.Y(f"{plot_col}:Q", title="Value"))
                        anoms = (
                            base.transform_filter(alt.datum.is_anom == True)
                            .mark_circle(size=70, color="red")
                            .encode(
                                y=alt.Y(f"{plot_col}:Q"),
                                tooltip=["ts:T", "value:N", "score:Q", "threshold:Q", "reason:N", "model:N", "vtype:N"],
                            )
                        )
                        st.altair_chart((line + anoms).interactive(), width="stretch")

                    elif chart_vtype == "cat":
                        st.dataframe(
                            df[["ts", "value", "score", "threshold", "is_anom", "reason", "model", "vtype"]].tail(100),
                            width="stretch",
                            hide_index=True,
                        )
                        anom_df = df[df["is_anom"] == True].copy()
                        if not anom_df.empty:
                            st.dataframe(
                                anom_df[["ts", "value", "score", "threshold", "reason", "model"]].tail(50),
                                width="stretch",
                                hide_index=True,
                            )

                with tabs[1]:
                    if {"score", "threshold"}.issubset(df.columns):
                        score_chart = (
                            alt.Chart(df)
                            .transform_fold(["score", "threshold"], as_=["metric", "val"])
                            .mark_line()
                            .encode(
                                x=alt.X("ts:T", title="Time"),
                                y=alt.Y("val:Q", title="Score / Threshold"),
                                color="metric:N",
                                tooltip=["ts:T", "metric:N", "val:Q"],
                            )
                        )
                        st.altair_chart(score_chart.interactive(), width="stretch")
                    else:
                        st.info("Score or threshold columns are unavailable.")

                tab_idx_rows = 2
                if chart_vtype == "numeric" and "prediction" in df.columns and df["prediction"].notna().any():
                    with tabs[2]:
                        pred_chart = (
                            alt.Chart(df)
                            .transform_fold(["plot_value", "prediction"], as_=["metric", "val"])
                            .mark_line()
                            .encode(
                                x=alt.X("ts:T", title="Time"),
                                y=alt.Y("val:Q", title="Actual / Prediction"),
                                color="metric:N",
                                tooltip=["ts:T", "metric:N", "val:Q"],
                            )
                        )
                        st.altair_chart(pred_chart.interactive(), width="stretch")

                        if "residual" in df.columns and df["residual"].notna().any():
                            residual_chart = (
                                alt.Chart(df)
                                .mark_line()
                                .encode(
                                    x=alt.X("ts:T", title="Time"),
                                    y=alt.Y("residual:Q", title="Residual"),
                                    tooltip=["ts:T", "residual:Q", "score:Q", "threshold:Q"],
                                )
                            )
                            st.altair_chart(residual_chart.interactive(), width="stretch")
                    tab_idx_rows = 3

                with tabs[tab_idx_rows]:
                    show_cols = [
                        c for c in [
                            "ts", "value", "prediction", "residual", "score",
                            "threshold", "is_anom", "reason", "model", "vtype"
                        ] if c in df.columns
                    ]
                    st.dataframe(df[show_cols].tail(100), width="stretch", hide_index=True)

    if uuid:
        with st.expander("AI assistant (selected UUID only)", expanded=False):
            ai_a, ai_b = st.columns([2, 1])

            with ai_a:
                st.text_input("AI model", key="ai_model")

            with ai_b:
                run_ai_now = st.button("Run analysis for selected UUID", width="stretch", key=f"run_ai_{uuid}")

            if not AI_API_KEY:
                st.warning("AI_API_KEY is not configured in the UI container.")
            else:
                recent_events = (recent_events_resp or {}).get("events", [])
                if run_ai_now:
                    with st.spinner("Running AI analysis..."):
                        result = run_ai_analysis_for_uuid(
                            uuid=uuid,
                            tag_item=selected_tag or {},
                            summary=detail or {},
                            snapshot_rows=snapshot_rows,
                            recent_events=recent_events,
                            model=st.session_state.ai_model,
                        )
                        st.session_state.ai_last_result = result
                        st.session_state.ai_last_uuid = uuid

                if st.session_state.ai_last_result and st.session_state.ai_last_uuid == uuid:
                    result = st.session_state.ai_last_result
                    if not result.get("ok"):
                        st.error(result.get("error", "AI analysis failed"))
                    else:
                        parsed = result.get("parsed")
                        if parsed and isinstance(parsed, dict):
                            st.json(parsed)
                        else:
                            st.text_area("Raw analysis", value=result.get("raw_text", ""), height=280)

                        with st.expander("AI payload used", expanded=False):
                            st.json(result.get("payload", {}))