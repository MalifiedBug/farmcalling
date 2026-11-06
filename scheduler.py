"""
Scheduler Module for FarmCalling.
Manages timed call executions using APScheduler and SQLite persistence.
Supports:
- One-time call at specific Date & Time
- Interval calls (every X minutes/hours/days)
- Recurring Cron calls (e.g. daily at 09:00)
- Immediate 'Call Now' triggers
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from database import (
    get_schedules,
    get_schedule,
    get_settings,
    get_effective_audio_id,
    update_schedule_status,
    update_schedule_run_info,
    create_call_log,
    update_call_log
)
from vobiz_client import VobizClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("farmcalling.scheduler")

scheduler: Optional[BackgroundScheduler] = None

def get_scheduler() -> BackgroundScheduler:
    global scheduler
    if scheduler is None:
        scheduler = BackgroundScheduler(timezone=pytz.timezone("Asia/Kolkata"))
        scheduler.start()
        logger.info("APScheduler initialized and started.")
    return scheduler

def execute_call_job(schedule_id: str):
    """
    Worker function invoked when a schedule trigger fires.
    Places outbound call via Vobiz API.
    """
    logger.info(f"Executing scheduled call for schedule_id: {schedule_id}")
    schedule = get_schedule(schedule_id)
    if not schedule:
        logger.warning(f"Schedule {schedule_id} not found in database.")
        return

    if schedule["status"] != "active":
        logger.info(f"Schedule {schedule_id} is {schedule['status']}, skipping call.")
        return

    settings = get_settings()
    auth_id = settings.get("auth_id", "").strip()
    auth_token = settings.get("auth_token", "").strip()
    caller_id = settings.get("caller_id", "").strip()
    base_url = settings.get("webhook_base_url", "").strip().rstrip("/")
    if not base_url or "example.com" in base_url or "localhost" in base_url or "127.0.0.1" in base_url:
        v_url = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL") or os.environ.get("VERCEL_URL") or os.environ.get("WEBHOOK_BASE_URL")
        if v_url:
            clean_v = v_url.strip().rstrip("/")
            base_url = f"https://{clean_v}" if not clean_v.startswith("http") else clean_v

    if not auth_id or not auth_token:
        logger.error("Vobiz credentials not configured. Cannot execute call.")
        create_call_log(
            to_number=schedule["to_number"],
            from_number=caller_id or "UNKNOWN",
            schedule_id=schedule_id,
            schedule_name=schedule["name"],
            status="failed",
            notes="Vobiz Auth ID / Auth Token not configured in Settings."
        )
        return

    if not caller_id:
        logger.error("No Outbound Caller ID configured.")
        create_call_log(
            to_number=schedule["to_number"],
            from_number="UNKNOWN",
            schedule_id=schedule_id,
            schedule_name=schedule["name"],
            status="failed",
            notes="No Outbound Caller ID specified in Settings."
        )
        return

    # Build webhook URLs
    audio_id = get_effective_audio_id(schedule.get("audio_id"))
    play_mode = schedule.get("play_mode", "audio")
    loop = schedule.get("loop_count", 1)

    answer_url = f"{base_url}/webhook/answer?schedule_id={schedule_id}&audio_id={audio_id}&play_mode={play_mode}&loop={loop}"
    hangup_url = f"{base_url}/webhook/hangup"

    # Create initial Call Log
    log_id = create_call_log(
        to_number=schedule["to_number"],
        from_number=caller_id,
        schedule_id=schedule_id,
        schedule_name=schedule["name"],
        audio_id=audio_id,
        status="queued",
        notes=f"Call initiated by schedule '{schedule['name']}'"
    )

    client = VobizClient(auth_id, auth_token)
    ring_timeout = int(settings.get("ring_timeout", "30"))
    time_limit = int(settings.get("time_limit", "3600"))
    amd = settings.get("machine_detection", "false")

    success, msg, data = client.make_call(
        from_number=caller_id,
        to_number=schedule["to_number"],
        answer_url=answer_url,
        hangup_url=hangup_url,
        ring_timeout=ring_timeout,
        time_limit=time_limit,
        machine_detection=amd
    )

    tz = pytz.timezone("Asia/Kolkata")
    now_iso = datetime.now(tz).isoformat()
    if success:
        call_uuid = data.get("request_uuid") or data.get("api_id")
        api_id = data.get("api_id")
        update_call_log(
            log_id=log_id,
            status="ringing",
            call_uuid=call_uuid,
            notes=f"Vobiz accepted call. API ID: {api_id}"
        )
        logger.info(f"Call placed successfully for schedule {schedule['name']}. UUID: {call_uuid}")
    else:
        update_call_log(
            log_id=log_id,
            status="failed",
            notes=f"Call failed: {msg}"
        )
        logger.error(f"Call failed for schedule {schedule['name']}: {msg}")

    # Update Schedule Next Run or Mark Completed
    sched_type = schedule.get("schedule_type")
    if sched_type == "once":
        update_schedule_status(schedule_id, "completed")
        update_schedule_run_info(schedule_id, last_run_at=now_iso, next_run_at=None)
    else:
        # Calculate next run timestamp in IST
        next_run = compute_next_run_ist(
            schedule_type=sched_type,
            cron_expression=schedule.get("cron_expression"),
            interval_value=schedule.get("interval_value"),
            interval_unit=schedule.get("interval_unit")
        )
        update_schedule_run_info(schedule_id, last_run_at=now_iso, next_run_at=next_run)

def compute_next_run_ist(
    schedule_type: str,
    cron_expression: Optional[str] = None,
    scheduled_datetime: Optional[str] = None,
    interval_value: Optional[int] = None,
    interval_unit: Optional[str] = None,
    base_time: Optional[datetime] = None
) -> Optional[str]:
    """
    Computes the exact next execution timestamp in Indian Standard Time (Asia/Kolkata, UTC+5:30).
    Returns ISO 8601 string with +05:30 offset, or None.
    """
    tz = pytz.timezone("Asia/Kolkata")
    now_ist = base_time or datetime.now(tz)

    try:
        if schedule_type == "once" and scheduled_datetime:
            run_dt = datetime.fromisoformat(str(scheduled_datetime).strip())
            if run_dt.tzinfo is None:
                run_dt = tz.localize(run_dt)
            else:
                run_dt = run_dt.astimezone(tz)
            return run_dt.isoformat() if run_dt > now_ist else None

        elif schedule_type == "interval":
            val = int(interval_value or 30)
            unit = interval_unit or "minutes"
            kwargs = {unit: val} if unit in ["minutes", "hours", "days"] else {"minutes": val}
            trigger = IntervalTrigger(**kwargs, timezone=tz, start_date=now_ist)
            nxt = trigger.get_next_fire_time(None, now_ist)
            return nxt.isoformat() if nxt else None

        elif schedule_type == "cron" and cron_expression:
            trigger = CronTrigger.from_crontab(str(cron_expression).strip(), timezone=tz)
            nxt = trigger.get_next_fire_time(None, now_ist)
            return nxt.isoformat() if nxt else None

    except Exception as e:
        logger.warning(f"Error computing next run IST for {schedule_type}: {e}")

    return None

def is_schedule_due_now(schedule: Dict[str, Any], tolerance_seconds: int = 120) -> bool:
    """
    Checks if an active schedule is due to fire right now in Indian Standard Time (Asia/Kolkata).
    """
    if schedule.get("status") != "active":
        return False

    tz = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(tz)
    sched_type = schedule.get("schedule_type")
    last_run = schedule.get("last_run_at")

    if sched_type == "once":
        dt_str = schedule.get("scheduled_datetime")
        if not dt_str:
            return False
        run_dt = datetime.fromisoformat(str(dt_str).strip())
        if run_dt.tzinfo is None:
            run_dt = tz.localize(run_dt)
        else:
            run_dt = run_dt.astimezone(tz)
        return now_ist >= run_dt and not last_run

    elif sched_type == "interval":
        val = int(schedule.get("interval_value") or 30)
        unit = schedule.get("interval_unit") or "minutes"
        interval_sec = val * (60 if unit == "minutes" else (3600 if unit == "hours" else 86400))
        if not last_run:
            return True
        last_dt = datetime.fromisoformat(str(last_run).strip())
        if last_dt.tzinfo is None:
            last_dt = tz.localize(last_dt)
        else:
            last_dt = last_dt.astimezone(tz)
        return (now_ist - last_dt).total_seconds() >= interval_sec

    elif sched_type == "cron":
        cron_expr = schedule.get("cron_expression")
        if not cron_expr:
            return False
        try:
            trigger = CronTrigger.from_crontab(str(cron_expr).strip(), timezone=tz)
            next_run = schedule.get("next_run_at")
            if next_run:
                next_dt = datetime.fromisoformat(str(next_run).strip())
                if next_dt.tzinfo is None:
                    next_dt = tz.localize(next_dt)
                else:
                    next_dt = next_dt.astimezone(tz)
                if now_ist >= next_dt:
                    if last_run and last_run[:16] == now_ist.isoformat()[:16]:
                        return False
                    return True

            fire = trigger.get_next_fire_time(None, now_ist - timedelta(seconds=tolerance_seconds))
            if fire and fire <= now_ist:
                if last_run and last_run[:16] == fire.isoformat()[:16]:
                    return False
                return True
        except Exception as e:
            logger.warning(f"Error evaluating cron {cron_expr} in IST: {e}")
            return False

    return False

def register_schedule_job(schedule_id: str, schedule_data: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Registers or updates an active schedule in APScheduler and sets next_run_at in IST.
    Returns: next_run_at ISO string in IST, or None.
    """
    schedule = schedule_data or get_schedule(schedule_id)
    if not schedule or schedule.get("status") != "active":
        return None

    sched = get_scheduler()

    # Remove existing job if present
    if sched.get_job(schedule_id):
        sched.remove_job(schedule_id)

    sched_type = schedule.get("schedule_type")
    tz = pytz.timezone("Asia/Kolkata")
    now_ist = datetime.now(tz)
    next_run_iso: Optional[str] = None

    try:
        if sched_type == "once":
            dt_str = schedule.get("scheduled_datetime")
            if dt_str:
                run_dt = datetime.fromisoformat(str(dt_str).strip())
                if run_dt.tzinfo is None:
                    run_dt = tz.localize(run_dt)
                else:
                    run_dt = run_dt.astimezone(tz)
                if run_dt > now_ist:
                    sched.add_job(
                        execute_call_job,
                        trigger=DateTrigger(run_date=run_dt, timezone=tz),
                        id=schedule_id,
                        args=[schedule_id],
                        replace_existing=True
                    )
                    next_run_iso = run_dt.isoformat()
                    logger.info(f"Registered one-time job for {run_dt} IST")
                else:
                    logger.info(f"Scheduled time {run_dt} IST is in the past, skipping registration.")

        elif sched_type == "interval":
            val = int(schedule.get("interval_value") or 30)
            unit = schedule.get("interval_unit") or "minutes"
            kwargs = {unit: val} if unit in ["minutes", "hours", "days"] else {"minutes": val}
            trigger = IntervalTrigger(**kwargs, timezone=tz, start_date=now_ist)
            job = sched.add_job(
                execute_call_job,
                trigger=trigger,
                id=schedule_id,
                args=[schedule_id],
                replace_existing=True
            )
            if job and job.next_run_time:
                next_run_iso = job.next_run_time.isoformat()
            logger.info(f"Registered interval job: every {val} {unit} (Next IST: {next_run_iso})")

        elif sched_type == "cron":
            cron_expr = schedule.get("cron_expression", "")
            parts = cron_expr.strip().split()
            if len(parts) == 5:
                trigger = CronTrigger.from_crontab(cron_expr.strip(), timezone=tz)
                job = sched.add_job(
                    execute_call_job,
                    trigger=trigger,
                    id=schedule_id,
                    args=[schedule_id],
                    replace_existing=True
                )
                if job and job.next_run_time:
                    next_run_iso = job.next_run_time.isoformat()
                else:
                    nxt = trigger.get_next_fire_time(None, now_ist)
                    next_run_iso = nxt.isoformat() if nxt else None
                logger.info(f"Registered cron job: {cron_expr} (Next IST: {next_run_iso})")

    except Exception as e:
        logger.error(f"Failed to register schedule {schedule_id}: {e}")

    # Fallback calculation if next_run_iso was not set by job
    if not next_run_iso:
        next_run_iso = compute_next_run_ist(
            schedule_type=sched_type,
            cron_expression=schedule.get("cron_expression"),
            scheduled_datetime=schedule.get("scheduled_datetime"),
            interval_value=schedule.get("interval_value"),
            interval_unit=schedule.get("interval_unit")
        )

    # Persist the calculated IST next run in the database
    if next_run_iso:
        try:
            update_schedule_run_info(
                schedule_id=schedule_id,
                last_run_at=schedule.get("last_run_at") or "",
                next_run_at=next_run_iso
            )
        except Exception as e:
            logger.warning(f"Could not persist next_run_at for {schedule_id}: {e}")

    return next_run_iso

def reload_all_schedules():
    """Syncs all active schedules from Database into APScheduler."""
    active_list = get_schedules(status_filter="active")
    logger.info(f"Reloading {len(active_list)} active schedules into APScheduler...")
    for item in active_list:
        register_schedule_job(item["id"], schedule_data=item)

def trigger_call_now(
    to_number: str,
    audio_id: Optional[str] = None,
    play_mode: str = "audio",
    tts_message: Optional[str] = None,
    loop_count: int = 1,
    schedule_name: str = "Instant Call",
    base_url_override: Optional[str] = None
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Immediately triggers an outbound call for testing or on-demand dialing.
    """
    settings = get_settings()
    auth_id = settings.get("auth_id", "").strip()
    auth_token = settings.get("auth_token", "").strip()
    caller_id = settings.get("caller_id", "").strip()
    loop_count = max(1, min(int(loop_count or 1), 10))

    base_url = (base_url_override or "").strip().rstrip("/")
    if not base_url or "example.com" in base_url or "localhost" in base_url or "127.0.0.1" in base_url:
        base_url = settings.get("webhook_base_url", "").strip().rstrip("/")
    if not base_url or "example.com" in base_url or "localhost" in base_url or "127.0.0.1" in base_url:
        v_url = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL") or os.environ.get("VERCEL_URL") or os.environ.get("WEBHOOK_BASE_URL")
        if v_url:
            clean_v = v_url.strip().rstrip("/")
            base_url = f"https://{clean_v}" if not clean_v.startswith("http") else clean_v

    if not auth_id or not auth_token:
        return False, "Vobiz Auth ID and Auth Token are missing. Please configure them in Settings.", {}
    if not caller_id:
        return False, "Outbound Caller ID (From number) is missing in Settings.", {}

    target_audio_id = get_effective_audio_id(audio_id)
    answer_url = f"{base_url}/webhook/answer?audio_id={target_audio_id}&play_mode={play_mode}&loop={loop_count}"
    hangup_url = f"{base_url}/webhook/hangup"

    log_id = create_call_log(
        to_number=to_number,
        from_number=caller_id,
        schedule_name=schedule_name,
        audio_id=target_audio_id,
        status="queued",
        notes="Triggered manually via Instant Call"
    )

    client = VobizClient(auth_id, auth_token)
    ring_timeout = int(settings.get("ring_timeout", "30"))
    time_limit = int(settings.get("time_limit", "3600"))
    amd = settings.get("machine_detection", "false")

    success, msg, data = client.make_call(
        from_number=caller_id,
        to_number=to_number,
        answer_url=answer_url,
        hangup_url=hangup_url,
        ring_timeout=ring_timeout,
        time_limit=time_limit,
        machine_detection=amd,
        caller_name="FarmCalling Automated Alert"
    )

    if success:
        call_uuid = data.get("request_uuid") or data.get("api_id")
        update_call_log(
            log_id=log_id,
            status="ringing",
            call_uuid=call_uuid,
            notes=f"Call accepted by Vobiz. Request UUID: {call_uuid}"
        )
        return True, "Call initiated successfully! Phone should ring shortly.", data
    else:
        update_call_log(
            log_id=log_id,
            status="failed",
            notes=f"Call failed: {msg}"
        )
        return False, msg, data
