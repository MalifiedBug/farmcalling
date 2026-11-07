"""
Settings Page: Vobiz Credentials, Application Provisioning, Webhooks, and Telephony Policy.
"""

import streamlit as st
import requests
import json
import pytz
import os

from database import (
    get_settings,
    update_settings,
    is_setting_env_managed,
    is_vobiz_env_configured,
    get_env_managed_keys,
    get_db_mode,
    is_postgres,
    db_execute,
    get_schedules,
    get_audio_assets
)
from vobiz_client import VobizClient

st.title("⚙️ System & Telephony Settings")
st.caption("Configure Vobiz API keys, register webhook applications, set caller IDs, and test connectivity.")

current_settings = get_settings()

tab_vobiz, tab_app, tab_webhook, tab_policy, tab_sim, tab_db = st.tabs([
    "🔑 Vobiz Credentials",
    "📱 Vobiz Application Sync",
    "🌐 Webhook & Tunneling",
    "⚙️ Call Policy & Audio",
    "🧪 Webhook Simulator",
    "🗄️ Database & Storage"
])

# ----------------- TAB 1: VOBIZ CREDENTIALS -----------------
with tab_vobiz:
    st.subheader("Vobiz API Authentication")

    env_configured = is_vobiz_env_configured()

    if env_configured:
        st.success("🔒 **Production Environment Configuration Active**")
        st.caption(
            "Vobiz credentials (`VOBIZ_AUTH_ID`, `VOBIZ_AUTH_TOKEN`, `VOBIZ_CALLER_ID`) are managed securely via "
            "environment variables. Manual web form input is locked to prevent accidental credential leakage or state loss."
        )

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Vobiz Auth ID", current_settings.get("auth_id", ""), help="Managed via VOBIZ_AUTH_ID")
        with c2:
            st.metric("Vobiz Auth Token", "••••••••••••••••", help="Protected in environment variables")
        with c3:
            st.metric("Default Caller ID", current_settings.get("caller_id") or "Not configured", help="Managed via VOBIZ_CALLER_ID")

        with st.expander("ℹ️ How to update production credentials"):
            st.markdown("""
            Credentials are controlled by environment variables:
            - **On Vercel:** Navigate to **Project Settings → Environment Variables** and update `VOBIZ_AUTH_ID`, `VOBIZ_AUTH_TOKEN`, or `VOBIZ_CALLER_ID`.
            - **In Local Development:** Edit your `.env` file in the project root:
              ```bash
              VOBIZ_AUTH_ID=MA_XXXXXXXXXXXX
              VOBIZ_AUTH_TOKEN=your_vobiz_auth_token
              VOBIZ_CALLER_ID=+919876543210
              ```
            """)
    else:
        st.info(
            "💡 **Production Best Practice:** Set `VOBIZ_AUTH_ID`, `VOBIZ_AUTH_TOKEN`, and `VOBIZ_CALLER_ID` "
            "in your environment (or `.env` file) so credentials are never entered or stored in the browser."
        )

        with st.form("creds_form"):
            auth_id = st.text_input(
                "Account Auth ID (`X-Auth-ID`)",
                value=current_settings.get("auth_id", ""),
                placeholder="e.g. MA_XXXXXX"
            )
            auth_token = st.text_input(
                "Account Auth Token (`X-Auth-Token`)",
                value=current_settings.get("auth_token", ""),
                type="password",
                placeholder="Your 32-character Auth Token"
            )
            caller_id = st.text_input(
                "Default Outbound Caller ID (`from`)",
                value=current_settings.get("caller_id", ""),
                placeholder="+919876543210 or 14155551234",
                help="Must be a verified Vobiz phone number or owned DID in E.164 format."
            )

            saved = st.form_submit_button("💾 Save Credentials (Local DB Only)", type="primary")

        if saved:
            update_settings({
                "auth_id": auth_id.strip(),
                "auth_token": auth_token.strip(),
                "caller_id": caller_id.strip()
            })
            st.success("Credentials saved to local database!")
            st.rerun()

    st.markdown("---")
    st.markdown("#### Test Vobiz Connection")
    if st.button("🔌 Verify Connection & Fetch Account Info", width="stretch"):
        client = VobizClient(
            current_settings.get("auth_id", ""),
            current_settings.get("auth_token", "")
        )
        with st.status("Testing connection with api.vobiz.ai...", expanded=True) as status_box:
            success, msg, data = client.test_connection()
            if success:
                status_box.update(label="✅ Connection Successful!", state="complete", expanded=True)
                st.success(msg)
                c_acc, c_bal = st.columns(2)
                with c_acc:
                    acc = data.get("account", {})
                    st.write(f"**Account Name:** `{acc.get('name') or acc.get('auth_id') or 'Active'}`")
                    st.write(f"**Account Status:** `{acc.get('status', 'Active')}`")
                with c_bal:
                    st.metric("Account Balance", f"{data.get('balance')} {data.get('currency')}")
                
                nums = data.get("numbers", [])
                if nums:
                    st.write(f"**Owned Phone Numbers ({len(nums)}):** {', '.join(nums)}")
                    if not current_settings.get("caller_id") and nums:
                        st.info(f"💡 Suggestion: You can set `{nums[0]}` as your default caller ID in your environment.")
            else:
                status_box.update(label="❌ Connection Failed", state="error", expanded=True)
                st.error(msg)

# ----------------- TAB 2: VOBIZ APPLICATION SYNC -----------------
with tab_app:
    st.subheader("Vobiz Application Management")
    st.markdown("A Vobiz Application binds your `answer_url` and `hangup_url` into a reusable app ID on the Vobiz network.")

    curr_app_id = current_settings.get("app_id", "")
    curr_app_name = current_settings.get("app_name", "FarmCalling-Voice-App")
    base_url = current_settings.get("webhook_base_url", "").rstrip("/")

    col_app1, col_app2 = st.columns(2)
    with col_app1:
        st.write(f"**Current App Name:** `{curr_app_name}`")
        st.write(f"**Vobiz App ID:** `{curr_app_id or 'Not Registered Yet'}`")
    with col_app2:
        st.write(f"**Target Answer URL:** `{base_url}/webhook/answer`")
        st.write(f"**Target Hangup URL:** `{base_url}/webhook/hangup`")

    st.markdown("---")
    st.markdown("#### One-Click Provision Application")
    st.caption("Automatically registers this app on your Vobiz account via `POST /api/v1/Account/{auth_id}/Application/`.")

    new_app_name = st.text_input("Application Name", value=curr_app_name)
    set_as_default = st.checkbox("Set as Default Number Application", value=False)

    if st.button("🚀 Register / Create Vobiz Application", type="primary"):
        client = VobizClient(
            current_settings.get("auth_id", ""),
            current_settings.get("auth_token", "")
        )
        if not client.is_configured():
            st.error("Please configure Vobiz Auth ID and Auth Token first in Tab 1.")
        elif not base_url or "example.com" in base_url:
            st.warning("Please configure your public Webhook Base URL in Tab 3 before registering.")
        else:
            with st.spinner("Registering Application with Vobiz..."):
                ok, msg, res_data = client.create_application(
                    app_name=new_app_name.strip(),
                    answer_url=f"{base_url}/webhook/answer",
                    hangup_url=f"{base_url}/webhook/hangup",
                    default_number_app=set_as_default
                )
                if ok:
                    new_app_id = res_data.get("app_id", "")
                    update_settings({
                        "app_name": new_app_name.strip(),
                        "app_id": new_app_id
                    })
                    st.success(f"Vobiz Application created! App ID: `{new_app_id}`")
                    st.rerun()
                else:
                    st.error(f"Failed to create application: {msg}")

    # List applications on account
    st.markdown("---")
    if st.button("📋 List Existing Applications on Account"):
        client = VobizClient(
            current_settings.get("auth_id", ""),
            current_settings.get("auth_token", "")
        )
        apps = client.list_applications()
        if apps:
            st.json(apps)
        else:
            st.info("No applications returned or account not reachable.")

# ----------------- TAB 3: WEBHOOK & TUNNELING -----------------
with tab_webhook:
    st.subheader("Webhook Public Base URL")
    st.markdown("Vobiz needs an **HTTPS URL** to fetch your call instructions (`answer_url`) and stream audio (`/audio/{id}`).")

    wh_is_env = is_setting_env_managed("webhook_base_url")
    if wh_is_env:
        st.success(f"🔒 **Webhook Public Base URL Configured via Environment:** `{current_settings.get('webhook_base_url')}`")
        if os.environ.get("VERCEL") or os.environ.get("VERCEL_URL"):
            st.caption("Automatically synced with your Vercel deployment HTTPS domain.")
    else:
        with st.form("webhook_form"):
            webhook_base = st.text_input(
                "Public Webhook Base URL",
                value=current_settings.get("webhook_base_url", "https://api.example.com"),
                help="Publicly accessible HTTPS URL pointing to your server port 8000."
            )
            save_wh = st.form_submit_button("💾 Save Webhook URL", type="primary")

        if save_wh:
            clean_url = webhook_base.strip().rstrip("/")
            update_settings({"webhook_base_url": clean_url})
            st.success("Webhook URL updated!")
            st.rerun()

    st.markdown("---")
    # Health check for internal server
    st.markdown("#### Internal Telephony Server Status")
    try:
        resp = requests.get("http://127.0.0.1:8000/health", timeout=2)
        if resp.status_code == 200:
            st.success("🟢 Local Webhook & Audio Server is RUNNING on `http://127.0.0.1:8000`")
        else:
            st.warning(f"🟡 Server returned HTTP {resp.status_code}")
    except Exception:
        st.error("🔴 Local Webhook Server is not responding on port 8000.")

    with st.expander("🌐 How to Expose Localhost to Vobiz (ngrok / Cloudflare / localtunnel)"):
        st.markdown("""
        Because Vobiz runs in the cloud, it must be able to reach your machine over HTTPS.
        
        **Option 1: Using ngrok (Recommended)**
        ```bash
        ngrok http 8000
        ```
        Copy the resulting HTTPS URL (e.g. `https://abc-123.ngrok-free.app`) and paste it above as your **Public Webhook Base URL**.

        **Option 2: Using localtunnel (No sign-up required)**
        ```bash
        npx localtunnel --port 8000
        ```

        **Option 3: Using Cloudflare Tunnel**
        ```bash
        cloudflared tunnel --url http://localhost:8000
        ```
        """)

# ----------------- TAB 4: CALL POLICY & AUDIO -----------------
with tab_policy:
    st.subheader("Outbound Call Policies & Default Prompts")

    with st.form("policy_form"):
        col_rt, col_tl = st.columns(2)
        with col_rt:
            ring_timeout = st.number_input(
                "Ring Timeout (seconds)",
                min_value=10, max_value=120,
                value=int(current_settings.get("ring_timeout", "30")),
                help="Maximum duration from start of ringing to hangup if recipient doesn't answer."
            )
        with col_tl:
            time_limit = st.number_input(
                "Maximum Call Duration (seconds)",
                min_value=60, max_value=14400,
                value=int(current_settings.get("time_limit", "3600")),
                help="Hard limit on call duration after being answered."
            )

        col_amd, col_tz = st.columns(2)
        with col_amd:
            amd_options = ["false", "true", "hangup"]
            curr_amd = current_settings.get("machine_detection", "false")
            amd_idx = amd_options.index(curr_amd) if curr_amd in amd_options else 0
            amd_selection = st.selectbox(
                "Answering Machine Detection (AMD)",
                amd_options,
                index=amd_idx,
                format_func=lambda x: "Disabled (false)" if x == "false" else ("Async Detection (true)" if x == "true" else "Hangup on Machine (hangup)")
            )
        with col_tz:
            common_tzs = ["Asia/Kolkata", "UTC", "America/New_York", "America/Los_Angeles", "Europe/London"]
            curr_tz = current_settings.get("timezone", "Asia/Kolkata")
            tz_idx = common_tzs.index(curr_tz) if curr_tz in common_tzs else 0
            timezone_selection = st.selectbox("Application Timezone", common_tzs, index=tz_idx)

        col_voice, col_vlang = st.columns(2)
        with col_voice:
            tts_voice = st.selectbox("Default TTS Voice", ["WOMAN", "MAN"], index=0 if current_settings.get("tts_default_voice", "WOMAN") == "WOMAN" else 1)
        with col_vlang:
            tts_lang = st.selectbox("Default TTS Language", ["en-US", "en-IN", "hi-IN", "en-GB"], index=0)

        saved_policy = st.form_submit_button("💾 Save Telephony Policies", type="primary")

    if saved_policy:
        update_settings({
            "ring_timeout": str(ring_timeout),
            "time_limit": str(time_limit),
            "machine_detection": amd_selection,
            "timezone": timezone_selection,
            "tts_default_voice": tts_voice,
            "tts_default_language": tts_lang
        })
        st.success("Telephony policies saved!")
        st.rerun()

# ----------------- TAB 5: WEBHOOK SIMULATOR -----------------
with tab_sim:
    st.subheader("🧪 Webhook Simulator")
    st.markdown("Simulate Vobiz webhook callbacks locally to verify VobizXML generation and hangup logging without making real calls.")

    col_sim1, col_sim2 = st.columns(2)
    with col_sim1:
        st.markdown("#### Test Answer Webhook (`POST /webhook/answer`)")
        sim_uuid = st.text_input("Simulated Call UUID", value="sim-call-999")
        if st.button("Simulate Call Answered"):
            try:
                r = requests.post(
                    "http://127.0.0.1:8000/webhook/answer",
                    data={"CallUUID": sim_uuid, "From": "+14155551234", "To": "+919876543210"}
                )
                st.write(f"HTTP Status: `{r.status_code}`")
                st.markdown("**VobizXML Response:**")
                st.code(r.text, language="xml")
            except Exception as e:
                st.error(f"Simulation failed: {e}")

    with col_sim2:
        st.markdown("#### Test Hangup Webhook (`POST /webhook/hangup`)")
        sim_dur = st.number_input("Simulated Duration (seconds)", min_value=1, max_value=600, value=25)
        sim_cause = st.selectbox("Hangup Cause", ["NORMAL_CLEARING", "USER_BUSY", "NO_ANSWER", "CALL_REJECTED"])
        if st.button("Simulate Call Hangup"):
            try:
                r = requests.post(
                    "http://127.0.0.1:8000/webhook/hangup",
                    data={"CallUUID": sim_uuid, "Duration": str(sim_dur), "HangupCause": sim_cause}
                )
                st.write(f"HTTP Status: `{r.status_code}`")
                st.json(r.json())
                st.success(f"Hangup recorded! Check Call History page to verify.")
            except Exception as e:
                st.error(f"Simulation failed: {e}")

# ----------------- TAB 6: DATABASE & STORAGE -----------------
with tab_db:
    st.subheader("Supabase PostgreSQL & Media Persistence")
    st.caption("Inspect database connectivity, persistent cloud tables, and audio storage.")

    db_mode = get_db_mode()
    is_pg = is_postgres()

    if is_pg:
        st.success("🟢 **Connected to Supabase PostgreSQL (Persistent Cloud Storage)**")
        st.caption("All schedules, call records, settings, and audio binaries (`BYTEA`) are stored permanently in Supabase.")
    else:
        st.warning("🟡 **Active Mode: SQLite (Local/Ephemeral)**")
        st.caption("Using local SQLite storage. Configure `DATABASE_URL` in environment variables or secrets to activate Supabase.")

    c_host, c_bucket, c_stat = st.columns(3)
    with c_host:
        st.metric("Database Host", "Supabase PostgreSQL", help="db.cvralbaxzcirpdnhgyus.supabase.co:5432")
    with c_bucket:
        st.metric("Storage Bucket", "farmcalling-audio", help="Supabase Public Audio Storage Bucket")
    with c_stat:
        st.metric("Persistence Status", "ACTIVE" if is_pg else "EPHEMERAL")

    st.markdown("---")
    st.markdown("#### Cloud Tables & Records in Database")

    try:
        schedules_cnt = len(get_schedules())
        audio_cnt = len(get_audio_assets())
        call_row = db_execute("SELECT count(*) as c FROM call_logs", fetch="one")
        call_cnt = call_row["c"] if call_row else 0
        sett_row = db_execute("SELECT count(*) as c FROM settings", fetch="one")
        sett_cnt = sett_row["c"] if sett_row else 0

        t1, t2, t3, t4 = st.columns(4)
        with t1:
            st.metric("Campaign Schedules", schedules_cnt)
        with t2:
            st.metric("Saved Audio Tracks", audio_cnt)
        with t3:
            st.metric("Call Logs (CDR)", call_cnt)
        with t4:
            st.metric("Configuration Keys", sett_cnt)
    except Exception as ex:
        st.error(f"Error querying table telemetry: {ex}")

    st.markdown("---")
    st.markdown("#### ⚡ 24/7 Autonomous Cloud Engine (`pg_cron` + `pg_net`)")
    st.caption("Ensures scheduled calls trigger automatically even when your browser, app, or computer is closed.")

    last_ping = settings.get("last_cron_ping_at", "Never")
    cron_endpoint = f"{settings.get('webhook_base_url', 'https://farmcalling2.vercel.app').rstrip('/')}/api/cron"

    c_cron1, c_cron2 = st.columns([1.5, 1.5])
    with c_cron1:
        st.write("• **Cloud Cron Engine:** Supabase Native (`pg_cron` + `pg_net`)")
        st.write("• **Heartbeat Cadence:** Every 60 seconds (`* * * * *`)")
        st.write(f"• **Target Webhook URL:** `{cron_endpoint}`")
    with c_cron2:
        st.write(f"• **Last Cloud Heartbeat:** `{last_ping.replace('T', ' ')[:19] if last_ping else 'Never'} IST`")
        st.write("• **Client Independence:** Runs 24/7 in AWS cloud with zero browser dependency")

    st.markdown("---")
    if st.button("🔄 Test Connection & Re-sync Tables", type="primary"):
        with st.status("Verifying Supabase PostgreSQL connection...", expanded=True) as status_box:
            try:
                row = db_execute("SELECT NOW() as current_time, current_database() as db_name, version() as v;", fetch="one")
                st.write(f"Database Name: `{row.get('db_name')}`")
                st.write(f"Supabase Server Time: `{row.get('current_time')}`")
                st.write(f"Engine Version: `{row.get('v')[:30]}...`")
                status_box.update(label="Supabase Connection Verified Successfully!", state="complete", expanded=True)
            except Exception as e:
                status_box.update(label=f"Connection Error: {e}", state="error")

