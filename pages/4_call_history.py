"""
Call History & CDR Analytics Page: Inspect Detailed Call Records and Telephony Metadata.
"""

import streamlit as st
import pandas as pd
import io
from database import get_call_logs

st.title("📊 Call Detail Records (CDR) & History")
st.caption("Inspect live call telemetry, durations, hangup reasons, and VobizXML executions.")

# Fetch logs
logs = get_call_logs(limit=200)

if not logs:
    st.info("No outbound calls recorded yet. Place an instant call or run a schedule to see telemetry.")
else:
    # Filter controls
    f_col1, f_col2, f_col3 = st.columns([1.5, 1, 1])
    with f_col1:
        search_query = st.text_input("🔍 Search by phone number or campaign", placeholder="e.g. +91 or Irrigation")
    with f_col2:
        status_filter = st.selectbox("Status Filter", ["All", "completed", "ringing", "in-progress", "busy", "no-answer", "failed"])
    with f_col3:
        st.write("")
        st.write("")
        df_export = pd.DataFrame(logs)
        csv_buffer = io.StringIO()
        df_export.to_csv(csv_buffer, index=False)
        st.download_button(
            label="📥 Export CSV",
            data=csv_buffer.getvalue(),
            file_name="farmcalling_call_logs.csv",
            mime="text/csv",
            width="stretch"
        )

    # Filter data
    filtered_logs = logs
    if status_filter != "All":
        filtered_logs = [l for l in filtered_logs if l["status"] == status_filter]
    if search_query.strip():
        q = search_query.strip().lower()
        filtered_logs = [
            l for l in filtered_logs
            if q in l.get("to_number", "").lower() or q in (l.get("schedule_name") or "").lower() or q in (l.get("call_uuid") or "").lower()
        ]

    # Metrics on filtered view
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Calls Displayed", len(filtered_logs))
    with c2:
        completed_c = sum(1 for l in filtered_logs if l["status"] == "completed")
        st.metric("Completed", completed_c)
    with c3:
        failed_c = sum(1 for l in filtered_logs if l["status"] in ["failed", "busy", "no-answer"])
        st.metric("Unsuccessful", failed_c)
    with c4:
        total_sec = sum(l.get("duration", 0) for l in filtered_logs)
        avg_sec = round(total_sec / len(filtered_logs), 1) if filtered_logs else 0
        st.metric("Avg Duration", f"{avg_sec}s")

    st.markdown("---")

    # Table View
    table_rows = []
    for l in filtered_logs:
        icon = "🟢" if l["status"] == "completed" else ("🟡" if l["status"] in ["ringing", "in-progress"] else "🔴")
        table_rows.append({
            "Status": f"{icon} {l['status'].upper()}",
            "Destination": l["to_number"],
            "Caller ID": l["from_number"],
            "Campaign": l.get("schedule_name") or "Instant Dial",
            "Duration": f"{l.get('duration', 0)}s",
            "Hangup Cause": l.get("hangup_cause") or "-",
            "Call UUID": (l.get("call_uuid") or "")[:12] + "...",
            "Initiated At": l["initiated_at"].replace("T", " ")[:19]
        })

    st.dataframe(pd.DataFrame(table_rows), width="stretch", hide_index=True)

    # Detailed Accordion / Inspection
    st.markdown("### 🔎 Call Record Inspector")
    for l in filtered_logs[:15]:
        status_icon = "🟢" if l["status"] == "completed" else ("🟡" if l["status"] in ["ringing", "in-progress"] else "🔴")
        with st.expander(f"{status_icon} {l['to_number']} — {l['initiated_at'].replace('T', ' ')[:19]} ({l.get('duration', 0)}s)"):
            c_det1, c_det2 = st.columns(2)
            with c_det1:
                st.markdown(f"**Call UUID:** `{l.get('call_uuid') or 'N/A'}`")
                st.markdown(f"**Vobiz API ID:** `{l.get('vobiz_api_id') or 'N/A'}`")
                st.markdown(f"**From (Caller ID):** `{l['from_number']}`")
                st.markdown(f"**To (Destination):** `{l['to_number']}`")
                st.markdown(f"**Campaign Name:** {l.get('schedule_name') or 'N/A'}")
            with c_det2:
                st.markdown(f"**Status:** `{l['status'].upper()}`")
                st.markdown(f"**Duration:** `{l.get('duration', 0)} seconds`")
                st.markdown(f"**Hangup Cause:** `{l.get('hangup_cause') or 'Pending/Normal'}`")
                st.markdown(f"**Initiated At:** `{l['initiated_at']}`")
                if l.get("ended_at"):
                    st.markdown(f"**Ended At:** `{l['ended_at']}`")
            
            if l.get("notes"):
                st.info(f"**Notes / Response:** {l['notes']}")

            if l.get("xml_rendered"):
                st.markdown("**Executed VobizXML:**")
                st.code(l["xml_rendered"], language="xml")

