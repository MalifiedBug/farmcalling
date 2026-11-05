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
    audio_id = schedule.get("audio_id") or settings.get("default_audio_id", "")
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

    now_iso = datetime.now().isoformat()
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
        # Calculate next run timestamp
        next_run = None
        job = get_scheduler().get_job(schedule_id)
        if job and job.next_run_time:
            next_run = job.next_run_time.isoformat()
        update_schedule_run_info(schedule_id, last_run_at=now_iso, next_run_at=next_run)

def register_schedule_job(schedule_id: str):
    """
    Registers or updates an active schedule in APScheduler.
    """
    schedule = get_schedule(schedule_id)
    if not schedule or schedule["status"] != "active":
        return

    sched = get_scheduler()

    # Remove existing job if present
    if sched.get_job(schedule_id):
        sched.remove_job(schedule_id)

    sched_type = schedule["schedule_type"]
    settings = get_settings()
    tz_str = settings.get("timezone", "Asia/Kolkata")
    try:
        tz = pytz.timezone(tz_str)
    except Exception:
        tz = pytz.timezone("Asia/Kolkata")

    try:
        if sched_type == "once":
            dt_str = schedule.get("scheduled_datetime")
            if dt_str:
                run_dt = datetime.fromisoformat(dt_str)
                if run_dt.tzinfo is None:
                    run_dt = tz.localize(run_dt)
                if run_dt > datetime.now(tz):
                    sched.add_job(
                        execute_call_job,
                        trigger=DateTrigger(run_date=run_dt, timezone=tz),
                        id=schedule_id,
                        args=[schedule_id],
                        replace_existing=True
                    )
                    logger.info(f"Registered one-time job for {run_dt}")
                else:
                    logger.info(f"Scheduled time {run_dt} is in the past, skipping registration.")

        elif sched_type == "interval":
            val = int(schedule.get("interval_value") or 30)
            unit = schedule.get("interval_unit") or "minutes"
            kwargs = {}
            if unit == "minutes":
                kwargs["minutes"] = val
            elif unit == "hours":
                kwargs["hours"] = val
            elif unit == "days":
                kwargs["days"] = val
            else:
                kwargs["minutes"] = val

            sched.add_job(
                execute_call_job,
                trigger=IntervalTrigger(**kwargs, timezone=tz),
                id=schedule_id,
                args=[schedule_id],
                replace_existing=True
            )
            logger.info(f"Registered interval job: every {val} {unit}")

        elif sched_type == "cron":
            cron_expr = schedule.get("cron_expression", "")
            parts = cron_expr.strip().split()
            if len(parts) == 5:
                sched.add_job(
                    execute_call_job,
                    trigger=CronTrigger.from_crontab(cron_expr, timezone=tz),
                    id=schedule_id,
                    args=[schedule_id],
                    replace_existing=True
                )
                logger.info(f"Registered cron job: {cron_expr}")

    except Exception as e:
        logger.error(f"Failed to register schedule {schedule_id}: {e}")

def reload_all_schedules():
    """Syncs all active schedules from SQLite into APScheduler."""
    active_list = get_schedules(status_filter="active")
    logger.info(f"Reloading {len(active_list)} active schedules into APScheduler...")
    for item in active_list:
        register_schedule_job(item["id"])

def trigger_call_now(
    to_number: str,
    audio_id: Optional[str] = None,
    play_mode: str = "audio",
    tts_message: Optional[str] = None,
    loop_count: int = 1,
    schedule_name: str = "Instant Call"
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Immediately triggers an outbound call for testing or on-demand dialing.
    """
    settings = get_settings()
    auth_id = settings.get("auth_id", "").strip()
    auth_token = settings.get("auth_token", "").strip()
    caller_id = settings.get("caller_id", "").strip()
    base_url = settings.get("webhook_base_url", "").strip().rstrip("/")

    if not auth_id or not auth_token:
        return False, "Vobiz Auth ID and Auth Token are missing. Please configure them in Settings.", {}
    if not caller_id:
        return False, "Outbound Caller ID (From number) is missing in Settings.", {}

    target_audio_id = audio_id or settings.get("default_audio_id", "")
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
