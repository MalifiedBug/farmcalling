"""
FarmCalling Background Telephony Daemon Worker.
Continuously polls and triggers due schedules in Indian Standard Time (Asia/Kolkata).
Usage:
    python daemon_worker.py
"""

import time
import logging
from datetime import datetime
import pytz
from database import get_schedules, get_settings, update_settings
from scheduler import execute_call_job, is_schedule_due_now

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("farmcalling.daemon")

def main():
    logger.info("=" * 60)
    logger.info("🚜 FarmCalling Telephony Daemon Worker Started")
    logger.info("Timezone: Indian Standard Time (Asia/Kolkata, UTC+5:30)")
    logger.info("Polling active campaigns every 15 seconds...")
    logger.info("=" * 60)

    tz = pytz.timezone("Asia/Kolkata")
    
    while True:
        try:
            now_ist = datetime.now(tz)
            now_iso = now_ist.isoformat()
            
            # Record daemon heartbeat
            try:
                update_settings({"last_cron_ping_at": now_iso})
            except Exception:
                pass

            schedules = get_schedules(status_filter="active")
            for s in schedules:
                try:
                    if is_schedule_due_now(s):
                        logger.info(f"⚡ Triggering due campaign in IST: {s.get('name')} (ID: {s.get('id')}) -> {s.get('to_number')}")
                        execute_call_job(s["id"])
                except Exception as e:
                    logger.error(f"Error evaluating schedule {s.get('id')}: {e}")

        except Exception as e:
            logger.error(f"Error in daemon cycle: {e}")

        time.sleep(15)

if __name__ == "__main__":
    main()

