"""
Database module for FarmCalling Vobiz Application.
Provides SQLite storage for settings, audio assets, schedules, and call logs.
"""

import sqlite3
import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
import uuid

logger = logging.getLogger(__name__)

def load_dotenv(dotenv_path: Optional[str] = None):
    """
    Parses a local .env file and sets values in os.environ if not already present.
    Supports comments (#), export statements, and quoted strings.
    """
    if dotenv_path is None:
        dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

    if not os.path.exists(dotenv_path):
        return

    try:
        with open(dotenv_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    val = v[1:-1]
                else:
                    val = v
                if k and k not in os.environ:
                    os.environ[k] = val
    except Exception as e:
        logger.warning(f"Failed to read .env file: {e}")

# Load .env immediately
load_dotenv()

ENV_SETTING_MAPPINGS = {
    "auth_id": ["VOBIZ_AUTH_ID"],
    "auth_token": ["VOBIZ_AUTH_TOKEN"],
    "caller_id": ["VOBIZ_CALLER_ID", "VOBIZ_FROM_NUMBER"],
    "webhook_base_url": ["WEBHOOK_BASE_URL", "VERCEL_PROJECT_PRODUCTION_URL", "VERCEL_URL"],
    "app_id": ["VOBIZ_APP_ID"],
    "app_name": ["VOBIZ_APP_NAME"],
    "ring_timeout": ["VOBIZ_RING_TIMEOUT", "RING_TIMEOUT"],
    "time_limit": ["VOBIZ_TIME_LIMIT", "TIME_LIMIT"],
    "machine_detection": ["VOBIZ_MACHINE_DETECTION", "MACHINE_DETECTION"],
    "timezone": ["VOBIZ_TIMEZONE", "TIMEZONE"],
    "default_audio_id": ["VOBIZ_DEFAULT_AUDIO_ID"],
    "tts_default_voice": ["VOBIZ_TTS_VOICE", "TTS_DEFAULT_VOICE"],
    "tts_default_language": ["VOBIZ_TTS_LANGUAGE", "TTS_DEFAULT_LANGUAGE"]
}

def get_env_override(key: str) -> Optional[str]:
    """
    Checks os.environ (and optionally Streamlit secrets) for an override.
    Normalizes URLs for webhook_base_url.
    """
    var_names = ENV_SETTING_MAPPINGS.get(key, [])
    for var in var_names:
        val = os.environ.get(var)
        if val is not None and str(val).strip():
            clean_val = str(val).strip()
            if key == "webhook_base_url":
                if not clean_val.startswith("http://") and not clean_val.startswith("https://"):
                    clean_val = f"https://{clean_val}"
                clean_val = clean_val.rstrip("/")
            return clean_val

    # Optional fallback to streamlit secrets if running under Streamlit
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            for var in var_names:
                if var in st.secrets and str(st.secrets[var]).strip():
                    clean_val = str(st.secrets[var]).strip()
                    if key == "webhook_base_url":
                        if not clean_val.startswith("http://") and not clean_val.startswith("https://"):
                            clean_val = f"https://{clean_val}"
                        clean_val = clean_val.rstrip("/")
                    return clean_val
    except Exception:
        pass

    return None

def is_setting_env_managed(key: str) -> bool:
    """Returns True if the setting is provided by an active environment variable."""
    return get_env_override(key) is not None

def is_vobiz_env_configured() -> bool:
    """Returns True if essential Vobiz credentials (auth_id and auth_token) come from environment."""
    return bool(get_env_override("auth_id") and get_env_override("auth_token"))

def get_env_managed_keys() -> List[str]:
    """Returns list of setting keys currently populated from environment variables."""
    return [k for k in ENV_SETTING_MAPPINGS if is_setting_env_managed(k)]

def get_db_path() -> str:
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return "/tmp/farmcalling.db"
    return os.path.join(os.path.dirname(__file__), "data", "farmcalling.db")

def get_connection() -> sqlite3.Connection:
    """Returns a SQLite connection with row_factory configured as Row."""
    db_path = get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes tables and default settings if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audio_assets (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        filename TEXT NOT NULL,
        filepath TEXT NOT NULL,
        mime_type TEXT NOT NULL,
        source_type TEXT NOT NULL,
        duration_seconds REAL DEFAULT 0,
        file_size_bytes INTEGER DEFAULT 0,
        tts_text TEXT,
        tts_voice TEXT,
        audio_bytes BLOB,
        external_url TEXT,
        created_at TEXT NOT NULL
    )
    """)

    # Migrations for existing SQLite files
    try:
        cursor.execute("ALTER TABLE audio_assets ADD COLUMN audio_bytes BLOB")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE audio_assets ADD COLUMN external_url TEXT")
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS schedules (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        to_number TEXT NOT NULL,
        schedule_type TEXT NOT NULL, -- 'once', 'interval', 'cron'
        scheduled_datetime TEXT,     -- 'YYYY-MM-DD HH:MM:SS'
        interval_value INTEGER,      -- e.g. 30
        interval_unit TEXT,          -- 'minutes', 'hours', 'days'
        cron_expression TEXT,        -- e.g. '0 9 * * *'
        audio_id TEXT,               -- reference to audio_assets.id
        play_mode TEXT DEFAULT 'audio', -- 'audio' or 'tts'
        tts_message TEXT,
        loop_count INTEGER DEFAULT 1,
        status TEXT DEFAULT 'active', -- 'active', 'paused', 'completed', 'error'
        last_run_at TEXT,
        next_run_at TEXT,
        total_runs INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS call_logs (
        id TEXT PRIMARY KEY,
        schedule_id TEXT,
        schedule_name TEXT,
        to_number TEXT NOT NULL,
        from_number TEXT NOT NULL,
        audio_id TEXT,
        call_uuid TEXT,
        vobiz_api_id TEXT,
        status TEXT DEFAULT 'queued', -- queued, ringing, in-progress, completed, failed, busy, no-answer
        initiated_at TEXT NOT NULL,
        answered_at TEXT,
        ended_at TEXT,
        duration INTEGER DEFAULT 0,
        hangup_cause TEXT,
        notes TEXT,
        xml_rendered TEXT
    )
    """)

    # Seed default settings, respecting environment variables if available
    default_settings = {
        "auth_id": get_env_override("auth_id") or "",
        "auth_token": get_env_override("auth_token") or "",
        "caller_id": get_env_override("caller_id") or "",
        "app_id": get_env_override("app_id") or "",
        "app_name": get_env_override("app_name") or "FarmCalling-Vobiz-App",
        "webhook_base_url": get_env_override("webhook_base_url") or "",
        "ring_timeout": get_env_override("ring_timeout") or "30",
        "time_limit": get_env_override("time_limit") or "3600",
        "machine_detection": get_env_override("machine_detection") or "false",
        "timezone": get_env_override("timezone") or "Asia/Kolkata",
        "default_audio_id": get_env_override("default_audio_id") or "test1-sample-id",
        "tts_default_voice": get_env_override("tts_default_voice") or "WOMAN",
        "tts_default_language": get_env_override("tts_default_language") or "en-US"
    }

    for key, val in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, str(val)))

    # Seed default audio assets if empty (guarantees audio availability on any serverless cold start)
    cursor.execute("SELECT COUNT(*) as cnt FROM audio_assets")
    count_row = cursor.fetchone()
    if not count_row or count_row["cnt"] == 0:
        static_audio_dir = os.path.join(os.path.dirname(__file__), "static", "audio")
        
        # 1. Seed test1.wav (user's real recording)
        t1_path = os.path.join(static_audio_dir, "test1.wav")
        t1_bytes = None
        if os.path.exists(t1_path):
            try:
                with open(t1_path, "rb") as f:
                    t1_bytes = f.read()
            except Exception as e:
                logger.warning(f"Could not read test1.wav for seeding: {e}")
        cursor.execute("""
            INSERT INTO audio_assets (
                id, name, filename, filepath, mime_type, source_type,
                duration_seconds, file_size_bytes, audio_bytes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "test1-sample-id",
            "test1 (Microphone Recording)",
            "test1.wav",
            t1_path,
            "audio/wav",
            "recorded",
            3.42,
            len(t1_bytes) if t1_bytes else 109484,
            t1_bytes,
            datetime.now().isoformat()
        ))

        # 2. Seed farm_alert.wav (chime announcement)
        fa_path = os.path.join(static_audio_dir, "farm_alert.wav")
        fa_bytes = None
        if os.path.exists(fa_path):
            try:
                with open(fa_path, "rb") as f:
                    fa_bytes = f.read()
            except Exception as e:
                logger.warning(f"Could not read farm_alert.wav for seeding: {e}")
        cursor.execute("""
            INSERT INTO audio_assets (
                id, name, filename, filepath, mime_type, source_type,
                duration_seconds, file_size_bytes, audio_bytes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "farm-alert-chime-id",
            "Farm Alert (Melodic Chime)",
            "farm_alert.wav",
            fa_path,
            "audio/wav",
            "upload",
            2.5,
            len(fa_bytes) if fa_bytes else 80000,
            fa_bytes,
            datetime.now().isoformat()
        ))

        # 3. Seed TTS asset
        cursor.execute("""
            INSERT INTO audio_assets (
                id, name, filename, filepath, mime_type, source_type,
                duration_seconds, file_size_bytes, tts_text, tts_voice, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "welcome-tts-id",
            "Default Farm Voice Notice (TTS)",
            "tts_virtual",
            "",
            "text/plain",
            "tts",
            0.0,
            0,
            "Hello! This is an automated voice announcement from FarmCalling. Have a productive day ahead. Goodbye.",
            "WOMAN",
            datetime.now().isoformat()
        ))

    conn.commit()
    conn.close()

# --- Settings Helpers ---

def get_settings() -> Dict[str, str]:
    """
    Returns settings dictionary.
    Environment variables ALWAYS take precedence over local database values,
    ensuring security and stateless operation in production/Vercel.
    """
    conn = get_connection()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    res = {row["key"]: row["value"] for row in rows}

    # Environment variables override database settings
    for key in ENV_SETTING_MAPPINGS:
        env_val = get_env_override(key)
        if env_val is not None:
            res[key] = env_val

    return res

def get_setting(key: str, default: str = "") -> str:
    """
    Gets a single setting value.
    Checks environment variables first, falling back to database and default.
    """
    env_val = get_env_override(key)
    if env_val is not None:
        return env_val

    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default

def update_settings(updates: Dict[str, Any]):
    """
    Updates settings in the local database.
    Keys actively managed by environment variables are skipped to prevent
    overwriting production configuration.
    """
    conn = get_connection()
    with conn:
        for key, val in updates.items():
            if is_setting_env_managed(key):
                logger.info(f"Skipping database update for '{key}' because it is managed by environment variable.")
                continue
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(val))
            )
    conn.close()

# --- Audio Assets Helpers ---

def add_audio_asset(
    name: str,
    filename: str,
    filepath: str,
    mime_type: str,
    source_type: str,
    duration_seconds: float = 0.0,
    file_size_bytes: int = 0,
    tts_text: Optional[str] = None,
    tts_voice: Optional[str] = None,
    audio_bytes: Optional[bytes] = None,
    external_url: Optional[str] = None
) -> str:
    asset_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    conn = get_connection()
    with conn:
        conn.execute("""
            INSERT INTO audio_assets (
                id, name, filename, filepath, mime_type, source_type,
                duration_seconds, file_size_bytes, tts_text, tts_voice,
                audio_bytes, external_url, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            asset_id, name, filename, filepath, mime_type, source_type,
            duration_seconds, file_size_bytes, tts_text, tts_voice,
            audio_bytes, external_url, now
        ))
    conn.close()
    return asset_id

def get_audio_assets() -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, name, filename, filepath, mime_type, source_type,
               duration_seconds, file_size_bytes, tts_text, tts_voice,
               external_url, (audio_bytes IS NOT NULL) AS has_audio_bytes, created_at
        FROM audio_assets
        ORDER BY created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_audio_asset(asset_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM audio_assets WHERE id = ?", (asset_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def delete_audio_asset(asset_id: str) -> bool:
    asset = get_audio_asset(asset_id)
    if not asset:
        return False
    # delete file from disk if exists
    if os.path.exists(asset["filepath"]):
        try:
            os.remove(asset["filepath"])
        except Exception:
            pass
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM audio_assets WHERE id = ?", (asset_id,))
    conn.close()
    return True

# --- Schedules Helpers ---

def create_schedule(
    name: str,
    to_number: str,
    schedule_type: str,
    scheduled_datetime: Optional[str] = None,
    interval_value: Optional[int] = None,
    interval_unit: Optional[str] = None,
    cron_expression: Optional[str] = None,
    audio_id: Optional[str] = None,
    play_mode: str = "audio",
    tts_message: Optional[str] = None,
    loop_count: int = 1,
    next_run_at: Optional[str] = None
) -> str:
    schedule_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    conn = get_connection()
    with conn:
        conn.execute("""
            INSERT INTO schedules (
                id, name, to_number, schedule_type, scheduled_datetime,
                interval_value, interval_unit, cron_expression, audio_id,
                play_mode, tts_message, loop_count, status, next_run_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """, (
            schedule_id, name, to_number, schedule_type, scheduled_datetime,
            interval_value, interval_unit, cron_expression, audio_id,
            play_mode, tts_message, loop_count, next_run_at, now
        ))
    conn.close()
    return schedule_id

def get_schedules(status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    if status_filter:
        rows = conn.execute("SELECT * FROM schedules WHERE status = ? ORDER BY created_at DESC", (status_filter,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM schedules ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_schedule(schedule_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def update_schedule_status(schedule_id: str, status: str):
    conn = get_connection()
    with conn:
        conn.execute("UPDATE schedules SET status = ? WHERE id = ?", (status, schedule_id))
    conn.close()

def update_schedule_run_info(schedule_id: str, last_run_at: str, next_run_at: Optional[str]):
    conn = get_connection()
    with conn:
        conn.execute("""
            UPDATE schedules 
            SET last_run_at = ?, next_run_at = ?, total_runs = total_runs + 1
            WHERE id = ?
        """, (last_run_at, next_run_at, schedule_id))
    conn.close()

def delete_schedule(schedule_id: str):
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
    conn.close()

# --- Call Logs Helpers ---

def create_call_log(
    to_number: str,
    from_number: str,
    schedule_id: Optional[str] = None,
    schedule_name: Optional[str] = None,
    audio_id: Optional[str] = None,
    call_uuid: Optional[str] = None,
    vobiz_api_id: Optional[str] = None,
    status: str = "queued",
    notes: Optional[str] = None,
    xml_rendered: Optional[str] = None
) -> str:
    log_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    conn = get_connection()
    with conn:
        conn.execute("""
            INSERT INTO call_logs (
                id, schedule_id, schedule_name, to_number, from_number,
                audio_id, call_uuid, vobiz_api_id, status, initiated_at,
                notes, xml_rendered
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log_id, schedule_id, schedule_name, to_number, from_number,
            audio_id, call_uuid, vobiz_api_id, status, now, notes, xml_rendered
        ))
    conn.close()
    return log_id

def update_call_log(
    log_id: str,
    status: Optional[str] = None,
    call_uuid: Optional[str] = None,
    answered_at: Optional[str] = None,
    ended_at: Optional[str] = None,
    duration: Optional[int] = None,
    hangup_cause: Optional[str] = None,
    notes: Optional[str] = None,
    xml_rendered: Optional[str] = None
):
    conn = get_connection()
    updates = []
    params = []
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if call_uuid is not None:
        updates.append("call_uuid = ?")
        params.append(call_uuid)
    if answered_at is not None:
        updates.append("answered_at = ?")
        params.append(answered_at)
    if ended_at is not None:
        updates.append("ended_at = ?")
        params.append(ended_at)
    if duration is not None:
        updates.append("duration = ?")
        params.append(duration)
    if hangup_cause is not None:
        updates.append("hangup_cause = ?")
        params.append(hangup_cause)
    if notes is not None:
        updates.append("notes = ?")
        params.append(notes)
    if xml_rendered is not None:
        updates.append("xml_rendered = ?")
        params.append(xml_rendered)

    if updates:
        params.append(log_id)
        sql = f"UPDATE call_logs SET {', '.join(updates)} WHERE id = ?"
        with conn:
            conn.execute(sql, params)
    conn.close()

def update_call_log_by_uuid(
    call_uuid: str,
    status: Optional[str] = None,
    answered_at: Optional[str] = None,
    ended_at: Optional[str] = None,
    duration: Optional[int] = None,
    hangup_cause: Optional[str] = None,
    notes: Optional[str] = None
):
    conn = get_connection()
    updates = []
    params = []
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if answered_at is not None:
        updates.append("answered_at = ?")
        params.append(answered_at)
    if ended_at is not None:
        updates.append("ended_at = ?")
        params.append(ended_at)
    if duration is not None:
        updates.append("duration = ?")
        params.append(duration)
    if hangup_cause is not None:
        updates.append("hangup_cause = ?")
        params.append(hangup_cause)
    if notes is not None:
        updates.append("notes = ?")
        params.append(notes)

    if updates:
        params.append(call_uuid)
        sql = f"UPDATE call_logs SET {', '.join(updates)} WHERE call_uuid = ?"
        with conn:
            conn.execute(sql, params)
    conn.close()

def get_call_logs(limit: int = 100) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM call_logs ORDER BY initiated_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_call_stats() -> Dict[str, Any]:
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) as c FROM call_logs").fetchone()["c"]
    completed = conn.execute("SELECT COUNT(*) as c FROM call_logs WHERE status = 'completed'").fetchone()["c"]
    failed = conn.execute("SELECT COUNT(*) as c FROM call_logs WHERE status IN ('failed', 'busy', 'no-answer')").fetchone()["c"]
    total_duration = conn.execute("SELECT SUM(duration) as s FROM call_logs").fetchone()["s"] or 0
    active_schedules = conn.execute("SELECT COUNT(*) as c FROM schedules WHERE status = 'active'").fetchone()["c"]
    conn.close()
    return {
        "total_calls": total,
        "completed_calls": completed,
        "failed_calls": failed,
        "total_duration_sec": total_duration,
        "active_schedules": active_schedules
    }

# Initialize on import
init_db()

