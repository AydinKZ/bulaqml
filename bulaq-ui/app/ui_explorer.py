import streamlit as st
from ui_helpers import make_tags_dataframe


def render_explorer(safe_get):
    with st.expander("Tag explorer", expanded=True):
        search_cols = st.columns([2, 1, 1, 1])

        with search_cols[0]:
            st.text_input("Search UUID", key="uuid_query", placeholder="type part of uuid/tag")

        with search_cols[1]:
            st.selectbox("VType filter", ["all", "numeric", "bool", "cat"], key="selected_vtype")

        with search_cols[2]:
            st.selectbox("Status filter", ["all", "discovered", "assigned", "active", "disabled"], key="selected_status")

        with search_cols[3]:
            st.selectbox("Rows", [25, 50, 100, 200], key="explorer_limit")

        params = {
            "q": st.session_state.get("uuid_query", ""),
            "vtype": st.session_state.get("selected_vtype", "all"),
            "status": st.session_state.get("selected_status", "all"),
            "limit": st.session_state.get("explorer_limit", 100),
        }

        tags_resp = safe_get("/learned-tags", params=params)
        tag_items = tags_resp.get("items", []) if tags_resp and "items" in tags_resp else []
        tags_df = make_tags_dataframe(tag_items)

        if tags_df.empty:
            st.info("No learned tags found for current filters.")
            st.session_state.selected_uuid = ""
            return ""

        compact_cols = [c for c in [
            "uuid",
            "vtype",
            "status",
            "assigned_model",
            "enabled_text",
            "runtime_text",
            "last_seen_text",
        ] if c in tags_df.columns]

        st.dataframe(tags_df[compact_cols], width="stretch", height=240)

        pick_cols = st.columns([3, 1])

        with pick_cols[0]:
            st.selectbox("Select UUID", tags_df["uuid"].tolist(), key="selected_uuid")

        return st.session_state.get("selected_uuid", "")