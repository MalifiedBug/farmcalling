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
    get_audio_asset,
    get_effective_audio_id,
    update_schedule_status,
    delete_schedule,
    get_settings
)
from scheduler import register_schedule_job, execute_call_job

st.title("⏱️ Automated Call Scheduling")
st.caption("Schedule voice calls on specific dates, recurring intervals, or daily timetables.")

# Data caching helpers for blazing fast UX
@st.cache_data(ttl=60)
def fetch_audio_assets():
    return get_audio_assets()

@st.cache_data(ttl=60)
def fetch_schedules():
    return get_schedules()

settings = get_settings()
tz_str = "Asia/Kolkata"
tz = pytz.timezone(tz_str)
now_tz = datetime.now(tz)

# Persistent activation alert banner
if "activation_banner" in st.session_state:
    b = st.session_state.pop("activation_banner")
    st.success(
        f"🎉 **Campaign Activated Successfully (IST)!**  \n"
        f"• **Campaign:** **{b['name']}**  \n"
        f"• **Recipient:** `{b['to']}` | **Type:** `{b['type']}` | **Repeat Count:** `{b['loops']}x`  \n"
        f"• **Next Scheduled Dial:** `{str(b['next_run']).replace('T', ' ')[:19]} IST` *(Asia/Kolkata / UTC+5:30)*",
        icon="✅"
    )

# 24/7 Cloud Background Execution Telemetry
last_ping = settings.get("last_cron_ping_at")
is_cloud_active = False
diff_mins = None
if last_ping:
    try:
        last_dt = datetime.fromisoformat(str(last_ping))
        if last_dt.tzinfo is None:
            last_dt = tz.localize(last_dt)
        diff_s = (now_tz - last_dt).total_seconds()
        is_cloud_active = diff_s < 180
        diff_mins = int(diff_s // 60)
    except Exception:
        pass

if is_cloud_active:
    st.info(
        "⚡ **24/7 Cloud Background Dialer Active**: Powered by Supabase `pg_cron` & `pg_net`. "
        "Your scheduled calls trigger automatically in Indian Standard Time (IST) even when this application, your browser, or your computer is closed! "
        f"*(Last cloud heartbeat: {diff_mins}m ago)*",
        icon="🌐"
    )
else:
    st.warning(
        "⚠️ **Cloud Heartbeat Idle**: No recent ping recorded within the last 3 minutes. "
        "Scheduled calls trigger when the dashboard is open or when `/api/cron` receives an external ping.",
        icon="⏰"
    )

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
            
            combined_dt = tz.localize(datetime.combine(sched_date, sched_time))
            scheduled_dt_str = combined_dt.isoformat()
            st.info(f"📅 Call will execute once on **{sched_date.strftime('%A, %b %d %Y')} at {sched_time.strftime('%I:%M %p')} IST** (Asia/Kolkata)")

        elif schedule_type == "Repeating Interval (Every X time)":
            c_val, c_unit = st.columns(2)
            with c_val:
                interval_val = st.number_input("Interval Frequency", min_value=1, max_value=365, value=30)
            with c_unit:
                interval_unit = st.selectbox("Unit", ["minutes", "hours", "days"], index=0)
            st.info(f"🔄 Call will execute **every {interval_val} {interval_unit}** continuously until paused.")

        else: # Daily / Recurring Cron
            st.markdown("##### 🗓️ Human-Friendly Recurrence Builder")
            c_freq, c_time_col = st.columns([1, 1])
            with c_freq:
                freq_choice = st.selectbox(
                    "How often should this call repeat?",
                    [
                        "Every Day (Daily)",
                        "Weekdays Only (Monday to Friday)",
                        "Weekends Only (Saturday & Sunday)",
                        "Specific Days of the Week",
                        "Twice Daily (Morning & Evening)",
                        "Monthly (On a specific day of the month)",
                        "Hourly (Every hour at specific minute)",
                        "Custom Cron Expression (Advanced)"
                    ]
                )

            cron_human_desc = ""

            if freq_choice == "Every Day (Daily)":
                with c_time_col:
                    t_val = st.time_input("Call Time", value=time(9, 0), key="daily_t")
                cron_expr = f"{t_val.minute} {t_val.hour} * * *"
                cron_human_desc = f"Every single day at **{t_val.strftime('%I:%M %p')}** ({tz_str})"

            elif freq_choice == "Weekdays Only (Monday to Friday)":
                with c_time_col:
                    t_val = st.time_input("Call Time (Mon - Fri)", value=time(9, 0), key="wd_t")
                cron_expr = f"{t_val.minute} {t_val.hour} * * 1-5"
                cron_human_desc = f"Every weekday (Monday to Friday) at **{t_val.strftime('%I:%M %p')}** ({tz_str})"

            elif freq_choice == "Weekends Only (Saturday & Sunday)":
                with c_time_col:
                    t_val = st.time_input("Call Time (Sat & Sun)", value=time(9, 0), key="we_t")
                cron_expr = f"{t_val.minute} {t_val.hour} * * 6,0"
                cron_human_desc = f"Every weekend (Saturday & Sunday) at **{t_val.strftime('%I:%M %p')}** ({tz_str})"

            elif freq_choice == "Specific Days of the Week":
                day_map = {
                    "Monday": 1, "Tuesday": 2, "Wednesday": 3,
                    "Thursday": 4, "Friday": 5, "Saturday": 6, "Sunday": 0
                }
                selected_days = st.multiselect(
                    "Select Target Days",
                    options=list(day_map.keys()),
                    default=["Monday", "Wednesday", "Friday"],
                    key="spec_days"
                )
                with c_time_col:
                    t_val = st.time_input("Call Time on Selected Days", value=time(9, 0), key="spec_t")

                day_nums = [str(day_map[d]) for d in selected_days]
                cron_days = ",".join(day_nums) if day_nums else "*"
                cron_expr = f"{t_val.minute} {t_val.hour} * * {cron_days}"
                day_names = ", ".join(selected_days) if selected_days else "Every day"
                cron_human_desc = f"Every **{day_names}** at **{t_val.strftime('%I:%M %p')}** ({tz_str})"

            elif freq_choice == "Twice Daily (Morning & Evening)":
                with c_time_col:
                    c_m, c_e = st.columns(2)
                    with c_m:
                        t_m = st.time_input("Morning Time", value=time(8, 0), key="td_m")
                    with c_e:
                        t_e = st.time_input("Evening Time", value=time(18, 0), key="td_e")
                cron_expr = f"{t_m.minute} {t_m.hour},{t_e.hour} * * *"
                cron_human_desc = f"Twice daily at **{t_m.strftime('%I:%M %p')}** and **{t_e.strftime('%I:%M %p')}** ({tz_str})"

            elif freq_choice == "Monthly (On a specific day of the month)":
                c_m_day, c_m_t = st.columns(2)
                with c_m_day:
                    m_day = st.number_input("Day of Month (1 - 31)", min_value=1, max_value=31, value=1, key="mon_day")
                with c_m_t:
                    t_val = st.time_input("Call Time", value=time(10, 0), key="mon_t")
                cron_expr = f"{t_val.minute} {t_val.hour} {m_day} * *"
                suff = "th" if 11 <= m_day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(m_day % 10, "th")
                cron_human_desc = f"On the **{m_day}{suff} of every month** at **{t_val.strftime('%I:%M %p')}** ({tz_str})"

            elif freq_choice == "Hourly (Every hour at specific minute)":
                with c_time_col:
                    m_val = st.number_input("At minute of every hour (0 - 59)", min_value=0, max_value=59, value=0, key="hrly_m")
                cron_expr = f"{m_val} * * * *"
                cron_human_desc = f"Every hour at **:{m_val:02d}** minutes past the hour ({tz_str})"

            else: # Custom Cron Expression (Advanced)
                with c_time_col:
                    cron_expr = st.text_input("5-part Cron Expression", value="0 9 * * 1-5", help="Format: minute hour day-of-month month day-of-week")
                cron_human_desc = f"Custom Schedule: `{cron_expr}` ({tz_str})"

            st.success(f"⏰ **Active Schedule:** Fires {cron_human_desc}  \n`Cron Expression: {cron_expr}`")

        st.markdown("#### 🎵 Audio Prompt & Playback Flow")
        audio_assets = fetch_audio_assets()
        effective_aid = get_effective_audio_id()
        audio_map = {}

        eff_asset = get_audio_asset(effective_aid)
        if eff_asset:
            eff_label = f"⭐ Active Prompt: {eff_asset['name']} ({eff_asset['source_type'].capitalize()})"
            audio_map[eff_label] = eff_asset["id"]

        for a in audio_assets:
            if a["id"] != effective_aid:
                label = f"{a['name']} ({a['source_type'].capitalize()})"
                audio_map[label] = a["id"]

        if not audio_map:
            audio_map = {"Default System Audio": "test1-sample-id"}

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

        submitted = st.form_submit_button("✨ Save & Activate Schedule (IST)", type="primary", width="stretch")

    if submitted:
        if not schedule_name.strip() or not to_number.strip():
            st.error("Schedule Name and Destination Phone Number are required.")
        else:
            s_type_key = "once" if "One-Off" in schedule_type else ("interval" if "Interval" in schedule_type else "cron")
            p_mode_key = "tts" if "TTS" in play_mode else "audio"

            with st.status("🚀 Saving & Activating Campaign in Indian Standard Time (IST)...", expanded=True) as status:
                st.write(f"Configuring schedule `{schedule_name}` in Asia/Kolkata timezone...")
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
                    loop_count=loops
                )
                st.write("Activating schedule in IST telephony engine...")
                next_run_ist = register_schedule_job(sched_id)
                status.update(label=f"Campaign '{schedule_name}' Activated in IST!", state="complete", expanded=False)

            st.session_state["activation_banner"] = {
                "name": schedule_name.strip(),
                "to": to_number.strip(),
                "next_run": next_run_ist or scheduled_dt_str or "Scheduled",
                "type": s_type_key.upper(),
                "loops": loops
            }
            st.cache_data.clear()
            st.rerun()

# Section 2: Manage Existing Schedules
st.markdown("---")

with st.container(border=True):
    col_stat1, col_stat2 = st.columns([3, 1])
    with col_stat1:
        st.markdown("##### ⚡ 24/7 Automated Dispatcher (IST)")
        last_cron_ping = settings.get("last_cron_ping_at")
        if last_cron_ping:
            st.caption(f"🟢 **Heartbeat Engine Active** | Last Ping: `{last_cron_ping[:19].replace('T', ' ')} IST`  \nMonitored continuously via GitHub Actions (every 5 min), free webhooks, and active browser tabs.")
        else:
            st.caption("ℹ️ **Heartbeat Engine Ready** | Monitored continuously via GitHub Actions (every 5 min), free webhooks, and active browser tabs.")
    with col_stat2:
        if st.button("⚡ Check & Dial Due Now", key="btn_force_cron", use_container_width=True):
            from scheduler import is_schedule_due_now, execute_call_job
            active_list = get_schedules(status_filter="active")
            triggered_any = []
            for item in active_list:
                if is_schedule_due_now(item):
                    execute_call_job(item["id"])
                    triggered_any.append(item["name"])
            st.cache_data.clear()
            if triggered_any:
                st.success(f"Dispatched {len(triggered_any)} due campaigns: {', '.join(triggered_any)}")
            else:
                st.info("Evaluated active campaigns in IST. No calls are due at this minute.")
            st.rerun()

st.subheader("📋 Scheduled Campaigns")

schedules = fetch_schedules()

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
                badge = "🟢 ACTIVE (IST)" if s["status"] == "active" else ("⏸️ PAUSED" if s["status"] == "paused" else "🏁 COMPLETED")
                st.markdown(f"**Status:** {badge}")
                st.caption(f"Total Runs: **{s['total_runs']}**")

            det_col1, det_col2, det_col3 = st.columns(3)
            with det_col1:
                if s["schedule_type"] == "once":
                    st.write(f"📅 **Target (IST):** `{s.get('scheduled_datetime', 'N/A')[:19].replace('T', ' ')}`")
                elif s["schedule_type"] == "interval":
                    st.write(f"🔄 **Cadence:** Every {s.get('interval_value')} {s.get('interval_unit')}")
                else:
                    st.write(f"⏰ **Cron (IST):** `{s.get('cron_expression')}`")
            with det_col2:
                next_run_disp = s.get("next_run_at")
                st.write(f"⏳ **Next Run (IST):** `{next_run_disp[:19].replace('T', ' ') if next_run_disp else 'Active'}`")
                st.caption(f"Audio: `{s.get('play_mode', 'audio').upper()}` ({s.get('loop_count', 1)}x)")
            with det_col3:
                last_run = s.get("last_run_at")
                st.write(f"🕒 **Last Run (IST):** {last_run[:19].replace('T', ' ') if last_run else 'Never'}")

            # Actions Row
            act1, act2, act3, _ = st.columns([1, 1, 1, 3])
            with act1:
                if st.button("⚡ Run Now", key=f"run_{s['id']}"):
                    with st.spinner("Executing scheduled call..."):
                        execute_call_job(s["id"])
                    st.cache_data.clear()
                    st.success("Call trigger sent!")
                    st.rerun()
            with act2:
                if s["status"] == "active":
                    if st.button("⏸️ Pause", key=f"pause_{s['id']}"):
                        update_schedule_status(s["id"], "paused")
                        st.cache_data.clear()
                        st.rerun()
                else:
                    if st.button("▶️ Resume", key=f"resume_{s['id']}"):
                        update_schedule_status(s["id"], "active")
                        register_schedule_job(s["id"])
                        st.cache_data.clear()
                        st.rerun()
            with act3:
                if st.button("🗑️ Delete", key=f"del_{s['id']}"):
                    delete_schedule(s["id"])
                    st.cache_data.clear()
                    st.success("Deleted schedule.")
                    st.rerun()

