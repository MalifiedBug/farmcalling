"""
FastAPI Server for FarmCalling (Vercel Serverless Ready).
Provides:
- Web dashboard at /
- Audio streaming endpoints for Vobiz (<Play> URL)
- Answer Webhook endpoint (returns VobizXML)
- Hangup Webhook endpoint (logs duration, status, hangup cause)
- Vercel Cron endpoint at /api/cron for scheduled dialer
- REST API for dashboard controls
"""

import os
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Request, Response, HTTPException, Query, Form, UploadFile, File
from fastapi.responses import FileResponse, PlainTextResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import (
    init_db,
    get_audio_asset,
    get_audio_assets,
    delete_audio_asset,
    get_schedule,
    get_schedules,
    create_schedule,
    delete_schedule,
    get_setting,
    get_settings,
    update_settings,
    is_setting_env_managed,
    is_vobiz_env_configured,
    get_env_managed_keys,
    update_call_log_by_uuid,
    create_call_log,
    update_call_log,
    get_call_logs,
    get_call_stats
)
from audio_manager import save_uploaded_audio, save_recorded_audio, create_tts_asset
from vobiz_client import VobizClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("farmcalling.server")

# Ensure DB is initialized
init_db()

app = FastAPI(title="FarmCalling Telephony Platform", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# --- Web UI ---
@app.get("/", response_class=HTMLResponse)
def index_page():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>FarmCalling API is running</h1>"

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "FarmCalling Telephony Engine",
        "vercel_serverless": bool(os.environ.get("VERCEL")),
        "timestamp": datetime.now().isoformat()
    }

# --- Audio Serving ---
@app.api_route("/audio/{asset_id}", methods=["GET", "HEAD"])
def serve_audio(asset_id: str):
    """
    High-reliability audio streaming endpoint for Vobiz (<Play> URL).
    Tiers:
    1. Database BLOB bytes (in-memory, works across any serverless instance)
    2. Filepath on disk (temporary or bundled)
    3. Bundled static audio (/static/audio/test1.wav, farm_alert.wav)
    4. Fallback chime (never returns 404 to Vobiz so calls never drop in silence)
    """
    logger.info(f"Serving audio request for asset_id: {asset_id}")

    # Tier 1: Look up in database
    asset = get_audio_asset(asset_id)
    if asset:
        # 1a. If raw audio_bytes BLOB exists in DB, serve directly from memory
        raw_bytes = asset.get("audio_bytes")
        if raw_bytes and len(raw_bytes) > 0:
            mime_type = asset.get("mime_type", "audio/wav")
            filename = asset.get("filename", f"{asset_id}.wav")
            return Response(
                content=raw_bytes,
                media_type=mime_type,
                headers={
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(len(raw_bytes)),
                    "Content-Disposition": f'inline; filename="{filename}"',
                    "Cache-Control": "public, max-age=3600"
                }
            )

        # 1b. If filepath on disk exists
        fp = asset.get("filepath", "")
        if fp and os.path.exists(fp):
            return FileResponse(
                path=fp,
                media_type=asset.get("mime_type", "audio/wav"),
                filename=asset.get("filename", f"{asset_id}.wav"),
                headers={"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=3600"}
            )

        # 1c. Try resolving filename in static/audio, data/audio, or /tmp/audio
        fname = asset.get("filename", "")
        if fname:
            for c_dir in [
                os.path.join(STATIC_DIR, "audio"),
                os.path.join(os.path.dirname(__file__), "data", "audio"),
                "/tmp/audio"
            ]:
                candidate = os.path.join(c_dir, fname)
                if os.path.exists(candidate):
                    return FileResponse(
                        path=candidate,
                        media_type=asset.get("mime_type", "audio/wav"),
                        headers={"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=3600"}
                    )

    # Tier 2: Check if asset_id is a direct filename (e.g. "test1.wav", "test1", "farm_alert.wav")
    clean_id = asset_id.strip()
    candidates = [clean_id]
    if not clean_id.endswith(".wav") and not clean_id.endswith(".mp3"):
        candidates.extend([f"{clean_id}.wav", f"{clean_id}.mp3"])

    for c_name in candidates:
        for c_dir in [
            os.path.join(STATIC_DIR, "audio"),
            os.path.join(os.path.dirname(__file__), "data", "audio"),
            "/tmp/audio"
        ]:
            candidate = os.path.join(c_dir, c_name)
            if os.path.exists(candidate):
                mtype = "audio/wav" if candidate.endswith(".wav") else "audio/mpeg"
                return FileResponse(
                    path=candidate,
                    media_type=mtype,
                    headers={"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=3600"}
                )

    # Tier 3: Infallible fallback - never return 404 to Vobiz during a live call!
    for fb_name in ["test1.wav", "farm_alert.wav"]:
        fb_path = os.path.join(STATIC_DIR, "audio", fb_name)
        if os.path.exists(fb_path):
            logger.warning(f"Audio asset '{asset_id}' not found; streaming fallback audio: {fb_name}")
            return FileResponse(
                path=fb_path,
                media_type="audio/wav",
                headers={"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=3600"}
            )

    raise HTTPException(status_code=404, detail=f"Audio asset '{asset_id}' not found")

# --- Vobiz Webhooks ---
@app.api_route("/webhook/answer", methods=["GET", "POST"])
async def answer_webhook(
    request: Request,
    schedule_id: Optional[str] = Query(None),
    audio_id: Optional[str] = Query(None),
    play_mode: Optional[str] = Query("audio"),
    loop: Optional[int] = Query(1)
):
    form_data = {}
    if request.method == "POST":
        try:
            raw_form = await request.form()
            form_data = dict(raw_form)
        except Exception:
            pass

    call_uuid = form_data.get("CallUUID") or request.query_params.get("CallUUID", "")
    from_num = form_data.get("From") or request.query_params.get("From", "")
    to_num = form_data.get("To") or request.query_params.get("To", "")

    # Auto-resolve base_url dynamically from incoming request if not configured
    settings = get_settings()
    base_url = settings.get("webhook_base_url", "").rstrip("/")
    if not base_url or "example.com" in base_url or "localhost" in base_url or "127.0.0.1" in base_url:
        host_header = request.headers.get("x-forwarded-host") or request.headers.get("host")
        if host_header:
            proto = request.headers.get("x-forwarded-proto", "https")
            base_url = f"{proto}://{host_header}"
        else:
            v_url = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL") or os.environ.get("VERCEL_URL")
            if v_url:
                base_url = f"https://{v_url}" if not v_url.startswith("http") else v_url

    schedule = get_schedule(schedule_id) if schedule_id else None
    target_audio_id = audio_id or (schedule.get("audio_id") if schedule else None) or settings.get("default_audio_id") or "test1-sample-id"
    target_play_mode = play_mode or (schedule.get("play_mode") if schedule else "audio")
    target_loop = loop if loop is not None else (schedule.get("loop_count", 1) if schedule else 1)

    xml_content = ""

    if target_play_mode == "tts" and schedule and schedule.get("tts_message"):
        tts_text = schedule.get("tts_message")
        voice = settings.get("tts_default_voice", "WOMAN")
        lang = settings.get("tts_default_language", "en-US")
        xml_content = VobizClient.generate_speak_xml(tts_text, voice=voice, language=lang, loop=target_loop)
    elif target_audio_id:
        # Check if direct URL (e.g. http:// or https://)
        if str(target_audio_id).startswith("http://") or str(target_audio_id).startswith("https://"):
            xml_content = VobizClient.generate_play_xml(str(target_audio_id), loop=target_loop)
        else:
            asset = get_audio_asset(target_audio_id)
            if asset and asset.get("source_type") == "tts" and asset.get("tts_text"):
                voice = asset.get("tts_voice") or settings.get("tts_default_voice", "WOMAN")
                xml_content = VobizClient.generate_speak_xml(asset["tts_text"], voice=voice, loop=target_loop)
            else:
                audio_public_url = f"{base_url}/audio/{target_audio_id}"
                xml_content = VobizClient.generate_play_xml(audio_public_url, loop=target_loop)
    else:
        audio_public_url = f"{base_url}/audio/test1-sample-id"
        xml_content = VobizClient.generate_play_xml(audio_public_url, loop=target_loop)

    if call_uuid:
        update_call_log_by_uuid(
            call_uuid=call_uuid,
            status="in-progress",
            answered_at=datetime.now().isoformat(),
            notes="Call answered. VobizXML dispatched."
        )

    return Response(content=xml_content, media_type="application/xml")

@app.api_route("/webhook/hangup", methods=["GET", "POST"])
async def hangup_webhook(request: Request):
    form_data = {}
    if request.method == "POST":
        try:
            raw_form = await request.form()
            form_data = dict(raw_form)
        except Exception:
            pass

    call_uuid = form_data.get("CallUUID") or request.query_params.get("CallUUID", "")
    call_status = form_data.get("CallStatus") or request.query_params.get("CallStatus", "completed")
    duration_str = form_data.get("Duration") or request.query_params.get("Duration", "0")
    hangup_cause = form_data.get("HangupCause") or request.query_params.get("HangupCause", "NORMAL_CLEARING")

    try:
        duration = int(duration_str)
    except ValueError:
        duration = 0

    if call_uuid:
        final_status = "completed"
        if hangup_cause in ["USER_BUSY", "CALL_REJECTED"]:
            final_status = "busy"
        elif hangup_cause in ["NO_ANSWER", "ORIGINATOR_CANCEL"]:
            final_status = "no-answer"
        elif "FAIL" in hangup_cause.upper() or "ERROR" in hangup_cause.upper():
            final_status = "failed"

        update_call_log_by_uuid(
            call_uuid=call_uuid,
            status=final_status,
            ended_at=datetime.now().isoformat(),
            duration=duration,
            hangup_cause=hangup_cause,
            notes=f"Call hung up with {hangup_cause} ({duration}s)"
        )

    return JSONResponse(content={"status": "acknowledged", "call_uuid": call_uuid})

# --- Vercel Cron Endpoint ---
@app.get("/api/cron")
@app.get("/cron")
def vercel_cron_handler():
    """
    Invoked periodically by Vercel Cron to process active schedules.
    """
    from scheduler import execute_call_job
    schedules = get_schedules(status_filter="active")
    now = datetime.now()
    triggered = []

    for s in schedules:
        sched_type = s["schedule_type"]
        is_due = False

        if sched_type == "once":
            dt_str = s.get("scheduled_datetime")
            if dt_str:
                try:
                    dt = datetime.fromisoformat(dt_str)
                    if dt <= now:
                        is_due = True
                except Exception:
                    pass

        elif sched_type == "interval":
            val = int(s.get("interval_value") or 30)
            unit = s.get("interval_unit") or "minutes"
            last_run = s.get("last_run_at")
            if not last_run:
                is_due = True
            else:
                try:
                    last_dt = datetime.fromisoformat(last_run)
                    delta_seconds = (now - last_dt).total_seconds()
                    interval_sec = val * (60 if unit == "minutes" else (3600 if unit == "hours" else 86400))
                    if delta_seconds >= interval_sec:
                        is_due = True
                except Exception:
                    pass

        elif sched_type == "cron":
            cron_expr = s.get("cron_expression", "")
            parts = cron_expr.strip().split()
            if len(parts) == 5:
                try:
                    t_min = int(parts[0]) if parts[0] != "*" else None
                    t_hr = int(parts[1]) if parts[1] != "*" else None
                    if (t_min is None or t_min == now.minute) and (t_hr is None or t_hr == now.hour):
                        last_run = s.get("last_run_at", "")
                        if not last_run or last_run[:16] != now.isoformat()[:16]:
                            is_due = True
                except Exception:
                    pass

        if is_due:
            logger.info(f"Vercel Cron executing due schedule: {s['name']} ({s['id']})")
            execute_call_job(s["id"])
            triggered.append(s["id"])

    return {
        "status": "success",
        "timestamp": now.isoformat(),
        "total_active_schedules": len(schedules),
        "triggered_count": len(triggered),
        "triggered_ids": triggered
    }

# --- REST API for Dashboard ---

@app.get("/api/stats")
def api_get_stats():
    return get_call_stats()

@app.get("/api/calls")
def api_get_calls(limit: int = 50):
    return get_call_logs(limit=limit)

class InstantCallPayload(BaseModel):
    to_number: str
    audio_id: Optional[str] = None
    play_mode: Optional[str] = "audio"
    tts_message: Optional[str] = None
    base_url: Optional[str] = None

@app.post("/api/calls/instant")
def api_trigger_instant_call(request: Request, payload: InstantCallPayload):
    from scheduler import trigger_call_now

    # Auto-resolve the exact public HTTPS domain from request or payload
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    proto = request.headers.get("x-forwarded-proto", "https")
    detected_base = payload.base_url or (f"{proto}://{host}" if host else None)

    p_mode = "tts" if payload.tts_message else (payload.play_mode or "audio")
    success, msg, data = trigger_call_now(
        to_number=payload.to_number,
        audio_id=payload.audio_id,
        play_mode=p_mode,
        tts_message=payload.tts_message,
        loop_count=1,
        schedule_name="Instant Dial",
        base_url_override=detected_base
    )
    return {"success": success, "message": msg, "data": data}

@app.get("/api/schedules")
def api_get_schedules():
    return get_schedules()

class CreateSchedulePayload(BaseModel):
    name: str
    to_number: str
    schedule_type: str
    scheduled_datetime: Optional[str] = None
    interval_value: Optional[int] = None
    interval_unit: Optional[str] = None
    cron_expression: Optional[str] = None
    audio_id: Optional[str] = None

@app.post("/api/schedules")
def api_create_schedule(payload: CreateSchedulePayload):
    sched_id = create_schedule(
        name=payload.name,
        to_number=payload.to_number,
        schedule_type=payload.schedule_type,
        scheduled_datetime=payload.scheduled_datetime,
        interval_value=payload.interval_value,
        interval_unit=payload.interval_unit,
        cron_expression=payload.cron_expression,
        audio_id=payload.audio_id,
        next_run_at=payload.scheduled_datetime
    )
    return {"success": True, "schedule_id": sched_id}

@app.delete("/api/schedules/{schedule_id}")
def api_delete_schedule(schedule_id: str):
    delete_schedule(schedule_id)
    return {"success": True}

@app.post("/api/schedules/{schedule_id}/run")
def api_run_schedule(schedule_id: str):
    from scheduler import execute_call_job
    execute_call_job(schedule_id)
    return {"success": True}

@app.get("/api/audio")
def api_get_audio():
    return get_audio_assets()

@app.post("/api/audio/upload")
async def api_upload_audio(audio_file: UploadFile = File(...), name: Optional[str] = Form(None)):
    content = await audio_file.read()
    aid = save_uploaded_audio(
        file_name=audio_file.filename,
        file_bytes=content,
        custom_name=name or audio_file.filename
    )
    return {"success": True, "audio_id": aid}

@app.delete("/api/audio/{asset_id}")
def api_delete_audio(asset_id: str):
    delete_audio_asset(asset_id)
    return {"success": True}

@app.get("/api/settings")
def api_get_settings():
    s = get_settings()
    env_keys = get_env_managed_keys()
    is_prod_env = is_vobiz_env_configured()
    res = dict(s)
    if "auth_token" in env_keys:
        res["auth_token"] = "••••••••••••••••"
    res["_env_managed_keys"] = env_keys
    res["_is_production_env"] = is_prod_env
    return res

@app.post("/api/settings")
def api_save_settings(data: Dict[str, Any]):
    env_keys = get_env_managed_keys()
    clean_data = {}
    for k, v in data.items():
        if k in env_keys:
            continue
        if k == "auth_token" and ("••••" in str(v) or not str(v).strip()):
            continue
        clean_data[k] = v
    if clean_data:
        update_settings(clean_data)
    return {"success": True, "updated_keys": list(clean_data.keys())}

@app.post("/api/settings/verify")
def api_verify_settings():
    s = get_settings()
    client = VobizClient(s.get("auth_id", ""), s.get("auth_token", ""))
    success, msg, data = client.test_connection()
    return {"success": success, "message": msg, "data": data}

@app.post("/api/settings/create-app")
def api_create_app():
    s = get_settings()
    client = VobizClient(s.get("auth_id", ""), s.get("auth_token", ""))
    base_url = s.get("webhook_base_url", "").rstrip("/")
    if not base_url or "example.com" in base_url:
        return {"success": False, "message": "Please configure a valid Public Webhook Base URL."}

    app_name = s.get("app_name", "FarmCalling-Voice-App")
    success, msg, data = client.create_application(
        app_name=app_name,
        answer_url=f"{base_url}/webhook/answer",
        hangup_url=f"{base_url}/webhook/hangup"
    )
    if success:
        app_id = data.get("app_id", "")
        update_settings({"app_id": app_id})
    return {"success": success, "message": msg, "data": data}
