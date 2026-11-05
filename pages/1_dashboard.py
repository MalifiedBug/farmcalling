"""
Dashboard Page: Live Telephony Operations, KPIs, and Instant Call Launcher.
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import requests

from database import (
    get_call_stats,
    get_call_logs,
    get_schedules,
    get_audio_assets,
    get_settings
)
from scheduler import trigger_call_now

st.title("📞 Telephony Operations Dashboard")
st.caption("Monitor automated outbound campaigns, inspect real-time metrics, and trigger instant calls.")

# 1. KPI Metrics
stats = get_call_stats()
col1, col2, col3, col4, col5 = st.columns(5)

total_calls = stats["total_calls"]
completed = stats["completed_calls"]
failed = stats["failed_calls"]
success_rate = round((completed / total_calls * 100), 1) if total_calls > 0 else 0.0

with col1:
    st.metric(label="Total Outbound Calls", value=total_calls)
with col2:
    st.metric(label="Completed Calls", value=completed, delta=f"{success_rate}% success")
with col3:
    st.metric(label="Failed / Busy", value=failed, delta_color="inverse")
with col4:
    st.metric(label="Total Call Time", value=f"{stats['total_duration_sec']}s")
with col5:
    st.metric(label="Active Schedules", value=stats["active_schedules"])

st.markdown("---")

# 2. Main content: Two Columns (Instant Dialer + Active Schedules)
left_col, right_col = st.columns([1.1, 0.9])

with left_col:
    st.subheader("⚡ Instant Call Launcher")
    st.markdown("Place a live test call immediately with your recorded audio or text-to-speech prompt.")

    settings = get_settings()
    configured = bool(settings.get("auth_id") and settings.get("auth_token") and settings.get("caller_id"))

    if not configured:
        st.warning("⚠️ Vobiz credentials or Outbound Caller ID not configured. Please visit **Settings** to set up your Auth ID and phone number.")

    with st.form("instant_call_form", clear_on_submit=False):
        to_phone = st.text_input(
            "Destination Phone Number (E.164 format)",
            placeholder="+919876543210 or 14155551234",
            help="Include country code, e.g. +91 for India or +1 for US/Canada."
        )

        audio_assets = get_audio_assets()
        audio_options = {"Default System Audio": ""}
        for a in audio_assets:
            label = f"{a['name']} ({a['source_type'].upper()} - {a['duration_seconds']}s)"
            audio_options[label] = a["id"]

        selected_audio_label = st.selectbox("Select Audio Prompt to Play", list(audio_options.keys()))
        selected_audio_id = audio_options[selected_audio_label]

        play_mode = st.radio("Playback Type", ["Audio File", "Custom Text-to-Speech (TTS)"], horizontal=True)

        tts_message = ""
        if play_mode == "Custom Text-to-Speech (TTS)":
            tts_message = st.text_area(
                "Text-to-Speech Script",
                value="Hello! This is a test alert from FarmCalling. Have a productive day! Goodbye.",
                height=80
            )

        loops = st.number_input("Audio Repeat Count (Loop)", min_value=1, max_value=5, value=1)

        submitted = st.form_submit_button("🚀 Dial Number Now", use_container_width=True, type="primary")

    if submitted:
        if not to_phone.strip():
            st.error("Please enter a valid destination phone number.")
        else:
            with st.status("Initiating Outbound Call via Vobiz API...", expanded=True) as status_box:
                st.write(f"Connecting to Vobiz API using Caller ID: `{settings.get('caller_id')}`")
                st.write(f"Dialing destination: `{to_phone.strip()}`")

                p_mode = "tts" if play_mode == "Custom Text-to-Speech (TTS)" else "audio"
                success, msg, data = trigger_call_now(
                    to_number=to_phone.strip(),
                    audio_id=selected_audio_id,
                    play_mode=p_mode,
                    tts_message=tts_message,
                    loop_count=loops,
                    schedule_name="Instant Test Call"
                )

                if success:
                    call_uuid = data.get("request_uuid") or data.get("api_id")
                    st.write(f"Call UUID: `{call_uuid}`")
                    st.write("Vobiz accepted the request. Destination will ring shortly.")
                    status_box.update(label="✅ Call Dispatched Successfully!", state="complete", expanded=False)
                    st.success(f"Success! {msg}")
                else:
                    st.write(f"Error details: {msg}")
                    status_box.update(label="❌ Call Dispatch Failed", state="error", expanded=True)
                    st.error(f"Call dispatch failed: {msg}")

with right_col:
    st.subheader("📅 Active Schedules")
    active_scheds = get_schedules(status_filter="active")

    if not active_scheds:
        st.info("No active schedules found. Create your first automated campaign in the **Schedules** page.")
    else:
        for s in active_scheds[:4]:
            with st.container(border=True):
                col_a, col_b = st.columns([2, 1])
                with col_a:
                    st.markdown(f"**{s['name']}**")
                    st.caption(f"Target: `{s['to_number']}` | Type: `{s['schedule_type'].capitalize()}`")
                with col_b:
                    st.caption(f"Runs: **{s['total_runs']}**")
                    if s.get("next_run_at"):
                        st.caption(f"Next: {s['next_run_at'].replace('T', ' ')[:16]}")
                    elif s.get("scheduled_datetime"):
                        st.caption(f"At: {s['scheduled_datetime'].replace('T', ' ')[:16]}")

# 3. Recent Call Activity
st.markdown("---")
st.subheader("📋 Recent Call Logs")

logs = get_call_logs(limit=10)
if not logs:
    st.info("No call logs recorded yet.")
else:
    table_data = []
    for log in logs:
        status_icon = "🟢" if log["status"] == "completed" else ("🟡" if log["status"] in ["ringing", "in-progress"] else "🔴")
        table_data.append({
            "Status": f"{status_icon} {log['status'].upper()}",
            "Destination": log["to_number"],
            "Campaign / Schedule": log.get("schedule_name") or "Instant Call",
            "Duration": f"{log.get('duration', 0)}s",
            "Hangup Cause": log.get("hangup_cause") or "-",
            "Time": log["initiated_at"].replace("T", " ")[:19]
        })

    df_logs = pd.DataFrame(table_data)
    st.dataframe(df_logs, use_container_width=True, hide_index=True)

