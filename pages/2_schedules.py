"""
Schedules Page: Create and Manage Automated Outbound Call Schedules.
Supports One-Time (Date & Time), Interval (every N min/hr/day), and Recurring Cron.
"""

import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
import pytz

from database import (
    create_schedule,
    get_schedules,
    get_audio_assets,
    update_schedule_status,
    delete_schedule,
    get_settings
)
from scheduler import register_schedule_job, execute_call_job

st.title("⏱️ Automated Call Scheduling")
st.caption("Schedule voice calls on specific dates, recurring intervals, or daily timetables.")

settings = get_settings()
tz_str = settings.get("timezone", "Asia/Kolkata")
try:
    tz = pytz.timezone(tz_str)
except Exception:
    tz = pytz.timezone("Asia/Kolkata")

now_tz = datetime.now(tz)

# Section 1: Create New Schedule
with st.expander("➕ Create New Call Schedule", expanded=True):
    with st.form("new_schedule_form"):
        col_name, col_phone = st.columns([1, 1])
        with col_name:
            schedule_name = st.text_input("Campaign / Schedule Name", placeholder="e.g. Morning Crop Irrigation Reminder")
        with col_phone:
            to_number = st.text_input(
                "Recipient Phone Number(s)",
                placeholder="+919876543210 (or separate multiple with <)",
                help="Vobiz accepts single E.164 numbers or bulk destinations separated by '<' (e.g. +919876543210<+919876543211)"
            )

        st.markdown("#### 🕒 Timing Configuration")
        schedule_type = st.radio(
            "Schedule Type",
            ["Specific Date & Time (One-Off)", "Repeating Interval (Every X time)", "Daily / Recurring Cron Schedule"],
            horizontal=True
        )

        scheduled_dt_str = None
        interval_val = None
        interval_unit = None
        cron_expr = None

        if schedule_type == "Specific Date & Time (One-Off)":
            c_date, c_time = st.columns(2)
            with c_date:
                sched_date = st.date_input("Target Date", value=now_tz.date(), min_value=now_tz.date())
            with c_time:
                # Default 5 minutes in future
                default_time = (now_tz + timedelta(minutes=5)).time()
                sched_time = st.time_input("Target Time", value=default_time)
            
            combined_dt = datetime.combine(sched_date, sched_time)
            scheduled_dt_str = combined_dt.isoformat()
            st.info(f"📅 Call will execute once on **{sched_date.strftime('%A, %b %d %Y')} at {sched_time.strftime('%I:%M %p')}** ({tz_str})")

        elif schedule_type == "Repeating Interval (Every X time)":
            c_val, c_unit = st.columns(2)
            with c_val:
                interval_val = st.number_input("Interval Frequency", min_value=1, max_value=365, value=30)
            with c_unit:
                interval_unit = st.selectbox("Unit", ["minutes", "hours", "days"], index=0)
            st.info(f"🔄 Call will execute **every {interval_val} {interval_unit}** continuously until paused.")

        else: # Daily / Recurring Cron
            c_cron_mode, c_cron_val = st.columns([1, 2])
            with c_cron_mode:
                cron_preset = st.selectbox("Preset", ["Daily at specific time", "Custom Cron Expression"])
            with c_cron_val:
                if cron_preset == "Daily at specific time":
                    daily_time = st.time_input("Time of day", value=time(9, 0))
                    cron_expr = f"{daily_time.minute} {daily_time.hour} * * *"
                    st.info(f"⏰ Call will fire every day at **{daily_time.strftime('%I:%M %p')}**")
                else:
                    cron_expr = st.text_input("5-part Cron Expression", value="0 9 * * 1-5", help="Standard cron: minute hour day month day-of-week")

        st.markdown("#### 🎵 Audio Prompt & Playback Flow")
        audio_assets = get_audio_assets()
        audio_map = {"[None / System Default]": ""}
        for a in audio_assets:
            label = f"{a['name']} ({a['source_type'].capitalize()})"
            audio_map[label] = a["id"]

        col_audio, col_mode = st.columns([2, 1])
        with col_audio:
            selected_audio_label = st.selectbox("Audio Clip to Play", list(audio_map.keys()))
            selected_audio_id = audio_map[selected_audio_label]
        with col_mode:
            play_mode = st.selectbox("Playback Mode", ["Recorded / Uploaded Audio", "Dynamic Text-to-Speech (TTS)"])

        tts_message = ""
        if play_mode == "Dynamic Text-to-Speech (TTS)":
            tts_message = st.text_area(
                "TTS Voice Message",
                value="Greetings from the farm management team. This is your scheduled automated broadcast. Goodbye."
            )

        col_loop, col_note = st.columns([1, 2])
        with col_loop:
            loops = st.number_input("Repeat Count (Loops)", min_value=1, max_value=10, value=1, help="Number of times to play audio before cutting the call (1 - 10).")
        with col_note:
            st.caption("ℹ️ Vobiz will play the chosen audio consecutively for the set repeat count, then hang up as per VobizXML `<Hangup/>` specifications.")

        submitted = st.form_submit_button("✨ Save & Activate Schedule", type="primary", width="stretch")

    if submitted:
        if not schedule_name.strip() or not to_number.strip():
            st.error("Schedule Name and Destination Phone Number are required.")
        else:
            s_type_key = "once" if "One-Off" in schedule_type else ("interval" if "Interval" in schedule_type else "cron")
            p_mode_key = "tts" if "TTS" in play_mode else "audio"

            sched_id = create_schedule(
                name=schedule_name.strip(),
                to_number=to_number.strip(),
                schedule_type=s_type_key,
                scheduled_datetime=scheduled_dt_str,
                interval_value=interval_val,
                interval_unit=interval_unit,
                cron_expression=cron_expr,
                audio_id=selected_audio_id,
                play_mode=p_mode_key,
                tts_message=tts_message,
                loop_count=loops,
                next_run_at=scheduled_dt_str
            )
            # Register in APScheduler
            register_schedule_job(sched_id)
            st.success(f"Schedule '{schedule_name}' created and activated successfully!")
            st.rerun()

# Section 2: Manage Existing Schedules
st.markdown("---")
st.subheader("📋 Scheduled Campaigns")

schedules = get_schedules()

if not schedules:
    st.info("No schedules found. Create one above to get started.")
else:
    for s in schedules:
        with st.container(border=True):
            head_col, status_col = st.columns([3, 1])
            with head_col:
                st.markdown(f"### {s['name']}")
                st.caption(f"📞 Destination: `{s['to_number']}` | Type: **{s['schedule_type'].upper()}**")
            with status_col:
                badge = "🟢 ACTIVE" if s["status"] == "active" else ("⏸️ PAUSED" if s["status"] == "paused" else "🏁 COMPLETED")
                st.markdown(f"**Status:** {badge}")
                st.caption(f"Total Runs: **{s['total_runs']}**")

            det_col1, det_col2, det_col3 = st.columns(3)
            with det_col1:
                if s["schedule_type"] == "once":
                    st.write(f"📅 **Run At:** {s.get('scheduled_datetime', 'N/A').replace('T', ' ')}")
                elif s["schedule_type"] == "interval":
                    st.write(f"🔄 **Every:** {s.get('interval_value')} {s.get('interval_unit')}")
                else:
                    st.write(f"⏰ **Cron:** `{s.get('cron_expression')}`")
            with det_col2:
                st.write(f"🎧 **Audio:** `{s.get('play_mode', 'audio').upper()}` (loops: {s.get('loop_count', 1)})")
            with det_col3:
                last_run = s.get("last_run_at")
                st.write(f"🕒 **Last Run:** {last_run[:19].replace('T', ' ') if last_run else 'Never'}")

            # Actions Row
            act1, act2, act3, _ = st.columns([1, 1, 1, 3])
            with act1:
                if st.button("⚡ Run Now", key=f"run_{s['id']}"):
                    with st.spinner("Executing scheduled call..."):
                        execute_call_job(s["id"])
                    st.success("Call trigger sent!")
                    st.rerun()
            with act2:
                if s["status"] == "active":
                    if st.button("⏸️ Pause", key=f"pause_{s['id']}"):
                        update_schedule_status(s["id"], "paused")
                        st.rerun()
                else:
                    if st.button("▶️ Resume", key=f"resume_{s['id']}"):
                        update_schedule_status(s["id"], "active")
                        register_schedule_job(s["id"])
                        st.rerun()
            with act3:
                if st.button("🗑️ Delete", key=f"del_{s['id']}"):
                    delete_schedule(s["id"])
                    st.success("Deleted schedule.")
                    st.rerun()

