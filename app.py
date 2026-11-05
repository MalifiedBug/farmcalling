"""
FarmCalling: Voice Calling & Scheduling Application powered by Vobiz.
Main Streamlit Application Entrypoint.
"""

import streamlit as st
import threading
import socket
import uvicorn
import logging

from database import init_db, get_settings, get_call_stats
from scheduler import get_scheduler, reload_all_schedules
from server import app as fastapi_app

def is_port_in_use(port: int = 8000) -> bool:
    """Checks if localhost port is already bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.05)
        return s.connect_ex(("127.0.0.1", port)) == 0

# 1. Page Configuration
st.set_page_config(
    page_title="FarmCalling | Vobiz Voice Automation",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2. Background Server & Scheduler Initializer
@st.cache_resource
def ensure_background_services():
    """Starts the FastAPI Webhook server on port 8000 and APScheduler once per session."""
    init_db()

    # Check if server is already running
    if not is_port_in_use(8000):
        def start_uvicorn():
            uvicorn.run(fastapi_app, host="0.0.0.0", port=8000, log_level="warning")

        server_thread = threading.Thread(target=start_uvicorn, daemon=True, name="FarmCallingFastAPIServer")
        server_thread.start()

    # Initialize Scheduler and load active jobs
    sched = get_scheduler()
    reload_all_schedules()
    return True

# Run service initialization
ensure_background_services()

# 3. Modern Multipage Navigation (Streamlit >= 1.36)
dashboard = st.Page("pages/1_dashboard.py", title="Operations Dashboard", icon="📊", default=True)
schedules_page = st.Page("pages/2_schedules.py", title="Schedules & Campaigns", icon="⏱️")
audio_page = st.Page("pages/3_audio_studio.py", title="Audio Studio & Library", icon="🎙️")
history_page = st.Page("pages/4_call_history.py", title="Call History (CDR)", icon="📋")
settings_page = st.Page("pages/5_settings.py", title="Settings & Vobiz API", icon="⚙️")

pg = st.navigation(
    {
        "Overview": [dashboard],
        "Telephony Engine": [schedules_page, audio_page, history_page],
        "Configuration": [settings_page]
    }
)

# 4. Sidebar Branding & System Telemetry
with st.sidebar:
    st.markdown("## 🌾 **FarmCalling**")
    st.caption("Automated Outbound Voice Platform powered by **Vobiz API**")
    st.markdown("---")

    settings = get_settings()
    configured = bool(settings.get("auth_id") and settings.get("auth_token"))

    # Server Status
    if is_port_in_use(8000):
        st.markdown("🖥️ **Server:** `🟢 Running (Port 8000)`")
    else:
        st.markdown("🖥️ **Server:** `🔴 Stopped`")

    # Vobiz Credentials Status
    if configured:
        st.markdown(f"🔑 **Vobiz Auth ID:** `{settings.get('auth_id')[:6]}...`")
        if settings.get("caller_id"):
            st.markdown(f"📱 **Caller ID:** `{settings.get('caller_id')}`")
        else:
            st.markdown("📱 **Caller ID:** `⚠️ Not set`")
    else:
        st.markdown("🔑 **Vobiz:** `⚠️ Needs Setup`")

    # Timezone
    st.caption(f"🌐 Timezone: `{settings.get('timezone', 'Asia/Kolkata')}`")

    st.markdown("---")
    st.caption("Built with Vobiz Applications API & VobizXML")

# 5. Render active page
pg.run()

