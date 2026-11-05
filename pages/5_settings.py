"""
Settings Page: Vobiz Credentials, Application Provisioning, Webhooks, and Telephony Policy.
"""

import streamlit as st
import requests
import json
import pytz

from database import get_settings, update_settings
from vobiz_client import VobizClient

st.title("⚙️ System & Telephony Settings")
st.caption("Configure Vobiz API keys, register webhook applications, set caller IDs, and test connectivity.")

current_settings = get_settings()

tab_vobiz, tab_app, tab_webhook, tab_policy, tab_sim = st.tabs([
    "🔑 Vobiz Credentials",
    "📱 Vobiz Application Sync",
    "🌐 Webhook & Tunneling",
    "⚙️ Call Policy & Audio",
    "🧪 Webhook Simulator"
])

# ----------------- TAB 1: VOBIZ CREDENTIALS -----------------
with tab_vobiz:
    st.subheader("Vobiz API Authentication")
    st.markdown("Enter your Vobiz credentials from the [Vobiz Console](https://console.vobiz.ai).")

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

        saved = st.form_submit_button("💾 Save Credentials", type="primary")

    if saved:
        update_settings({
            "auth_id": auth_id.strip(),
            "auth_token": auth_token.strip(),
            "caller_id": caller_id.strip()
        })
        st.success("Credentials saved to database!")
        st.rerun()

    st.markdown("---")
    st.markdown("#### Test Vobiz Connection")
    if st.button("🔌 Verify Connection & Fetch Account Info", use_container_width=True):
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
                        st.info(f"💡 Suggestion: You can set `{nums[0]}` as your default caller ID.")
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

