"""
Database module for FarmCalling Vobiz Application.
Provides SQLite storage for settings, audio assets, schedules, and call logs.
"""

import sqlite3
import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
import uuid

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
        created_at TEXT NOT NULL
    )
    """)

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

    # Seed default settings if empty
    # Seed default settings, respecting environment variables if available
    auth_id_env = os.environ.get("VOBIZ_AUTH_ID", "")
    auth_token_env = os.environ.get("VOBIZ_AUTH_TOKEN", "")
    caller_id_env = os.environ.get("VOBIZ_CALLER_ID", "")
    vercel_url = os.environ.get("VERCEL_URL") or os.environ.get("WEBHOOK_BASE_URL", "")
    if vercel_url and not vercel_url.startswith("http"):
        vercel_url = f"https://{vercel_url}"

    default_settings = {
        "auth_id": auth_id_env,
        "auth_token": auth_token_env,
        "caller_id": caller_id_env,
        "app_id": "",
        "app_name": "FarmCalling-Vobiz-App",
        "webhook_base_url": vercel_url or "https://api.example.com",
        "ring_timeout": "30",
        "time_limit": "3600",
        "machine_detection": "false",
        "timezone": "Asia/Kolkata",
        "default_audio_id": "",
        "tts_default_voice": "WOMAN",
        "tts_default_language": "en-US"
    }

    for key, val in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, str(val)))

    conn.commit()
    conn.close()

# --- Settings Helpers ---

def get_settings() -> Dict[str, str]:
    conn = get_connection()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    res = {row["key"]: row["value"] for row in rows}

    # Fallback to environment variables if empty
    if not res.get("auth_id") and os.environ.get("VOBIZ_AUTH_ID"):
        res["auth_id"] = os.environ.get("VOBIZ_AUTH_ID")
    if not res.get("auth_token") and os.environ.get("VOBIZ_AUTH_TOKEN"):
        res["auth_token"] = os.environ.get("VOBIZ_AUTH_TOKEN")
    if not res.get("caller_id") and os.environ.get("VOBIZ_CALLER_ID"):
        res["caller_id"] = os.environ.get("VOBIZ_CALLER_ID")
    if not res.get("webhook_base_url") or "example.com" in res.get("webhook_base_url", ""):
        v_url = os.environ.get("VERCEL_URL") or os.environ.get("WEBHOOK_BASE_URL")
        if v_url:
            res["webhook_base_url"] = v_url if v_url.startswith("http") else f"https://{v_url}"
    return res

def get_setting(key: str, default: str = "") -> str:
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default

def update_settings(updates: Dict[str, Any]):
    conn = get_connection()
    with conn:
        for key, val in updates.items():
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
    tts_voice: Optional[str] = None
) -> str:
    asset_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    conn = get_connection()
    with conn:
        conn.execute("""
            INSERT INTO audio_assets (
                id, name, filename, filepath, mime_type, source_type,
                duration_seconds, file_size_bytes, tts_text, tts_voice, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            asset_id, name, filename, filepath, mime_type, source_type,
            duration_seconds, file_size_bytes, tts_text, tts_voice, now
        ))
    conn.close()
    return asset_id

def get_audio_assets() -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM audio_assets ORDER BY created_at DESC").fetchall()
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

