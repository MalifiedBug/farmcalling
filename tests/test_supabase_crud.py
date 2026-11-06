"""
Dedicated Test Suite for Supabase PostgreSQL Persistence & CRUD Operations.
Verifies all data models and media bytes are stored, retrieved, and deleted
directly from Supabase PostgreSQL.
"""

import unittest
import os
import uuid
from datetime import datetime

# Explicitly ensure we connect to Supabase PostgreSQL (do not set USE_SQLITE)
os.environ.pop("USE_SQLITE", None)

from database import (
    get_db_mode,
    is_postgres,
    get_settings,
    update_settings,
    get_setting,
    add_audio_asset,
    get_audio_assets,
    get_audio_asset,
    get_audio_bytes,
    delete_audio_asset,
    create_schedule,
    get_schedules,
    get_schedule,
    update_schedule_status,
    delete_schedule,
    create_call_log,
    update_call_log_by_uuid,
    get_call_logs,
    get_call_stats,
    get_effective_audio_id,
    get_latest_custom_audio_id,
    db_execute
)

class TestSupabasePersistence(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Reset any in-memory sqlite caching from previous unit tests
        os.environ.pop("USE_SQLITE", None)
        import database
        database._db_mode = None
        database._pg_conn = None
        database._active_pg_url = None
        database.init_db()

    def test_01_backend_is_supabase_postgres(self):
        """Verifies active backend is Supabase PostgreSQL."""
        mode = get_db_mode()
        self.assertEqual(mode, "postgres", f"Expected 'postgres' backend, got '{mode}'")
        self.assertTrue(is_postgres())

    def test_02_settings_crud_in_supabase(self):
        """Verifies settings CRUD persists directly in Supabase."""
        test_key = f"test_supabase_key_{uuid.uuid4().hex[:8]}"
        test_val = f"val_{uuid.uuid4().hex}"

        update_settings({test_key: test_val})
        fetched = get_setting(test_key)
        self.assertEqual(fetched, test_val, "Setting value did not match in Supabase")

        # Clean up test key
        db_execute("DELETE FROM settings WHERE key = ?", (test_key,))

    def test_03_audio_media_crud_and_bytes_in_supabase(self):
        """Verifies audio binary media is stored as BYTEA in Supabase and retrieved byte-perfect."""
        sample_pcm_bytes = b"RIFF" + b"\x00" * 40 + b"WAVEfmt " + b"\x00" * 500
        custom_name = f"Supabase Audio Test {uuid.uuid4().hex[:6]}"

        aid = add_audio_asset(
            name=custom_name,
            filename=f"test_{uuid.uuid4().hex[:8]}.wav",
            filepath=f"/tmp/test_{uuid.uuid4().hex[:8]}.wav",
            mime_type="audio/wav",
            source_type="upload",
            duration_seconds=5.0,
            file_size_bytes=len(sample_pcm_bytes),
            audio_bytes=sample_pcm_bytes
        )
        self.assertTrue(aid)

        # Retrieve asset metadata
        asset = get_audio_asset(aid)
        self.assertIsNotNone(asset)
        self.assertEqual(asset["name"], custom_name)
        self.assertIn("supabase.co/storage", asset["external_url"])

        # Retrieve raw binary bytes directly from Supabase
        fetched_bytes = get_audio_bytes(aid)
        self.assertIsNotNone(fetched_bytes)
        self.assertEqual(len(fetched_bytes), len(sample_pcm_bytes))
        self.assertEqual(fetched_bytes, sample_pcm_bytes)

        # Delete asset from Supabase
        del_result = delete_audio_asset(aid)
        self.assertTrue(del_result)
        self.assertIsNone(get_audio_asset(aid))

    def test_04_schedule_crud_in_supabase(self):
        """Verifies schedule campaigns CRUD persists in Supabase."""
        sched_name = f"Supabase Sched {uuid.uuid4().hex[:6]}"
        sched_id = create_schedule(
            name=sched_name,
            to_number="+919321089065",
            schedule_type="once",
            scheduled_datetime="2026-12-01T10:00:00"
        )
        self.assertTrue(sched_id)

        # Read back
        sched = get_schedule(sched_id)
        self.assertIsNotNone(sched)
        self.assertEqual(sched["name"], sched_name)
        self.assertEqual(sched["to_number"], "+919321089065")
        self.assertEqual(sched["status"], "active")

        # Update status
        update_schedule_status(sched_id, "paused")
        sched_paused = get_schedule(sched_id)
        self.assertEqual(sched_paused["status"], "paused")

        # Delete
        delete_schedule(sched_id)
        self.assertIsNone(get_schedule(sched_id))

    def test_05_call_logs_crud_in_supabase(self):
        """Verifies CDR call logs persist in Supabase."""
        test_uuid = f"uuid-{uuid.uuid4()}"
        log_id = create_call_log(
            to_number="+919321089065",
            from_number="+918065354878",
            schedule_name="Test Broadcast",
            call_uuid=test_uuid,
            status="ringing"
        )
        self.assertTrue(log_id)

        # Update by UUID (as webhook does)
        update_call_log_by_uuid(
            call_uuid=test_uuid,
            status="completed",
            duration=42,
            hangup_cause="NORMAL_CLEARING"
        )

        logs = get_call_logs(limit=20)
        found = next((l for l in logs if l.get("call_uuid") == test_uuid), None)
        self.assertIsNotNone(found)
        self.assertEqual(found["status"], "completed")
        self.assertEqual(found["duration"], 42)

        # Clean up test log
        db_execute("DELETE FROM call_logs WHERE id = ?", (log_id,))

    def test_06_effective_audio_selection_and_auto_default(self):
        """Verifies custom uploaded audio is automatically prioritized and set as default."""
        sample_bytes = b"RIFF" + b"\x00" * 40 + b"WAVEfmt " + b"\x00" * 1000
        test_audio_name = f"Farmer Broadcast Test {uuid.uuid4().hex[:6]}"

        aid = add_audio_asset(
            name=test_audio_name,
            filename=f"farmer_{uuid.uuid4().hex[:8]}.wav",
            filepath=f"/tmp/farmer_{uuid.uuid4().hex[:8]}.wav",
            mime_type="audio/wav",
            source_type="upload",
            duration_seconds=3.5,
            file_size_bytes=len(sample_bytes),
            audio_bytes=sample_bytes
        )
        try:
            # 1. Check auto-set default in settings
            curr_def = get_setting("default_audio_id")
            self.assertEqual(curr_def, aid)

            # 2. Check get_effective_audio_id without params
            eff_id = get_effective_audio_id()
            self.assertEqual(eff_id, aid)

            # 3. Check get_effective_audio_id with empty/placeholder params
            self.assertEqual(get_effective_audio_id(""), aid)
            self.assertEqual(get_effective_audio_id("[None / System Default]"), aid)

            # 4. Check asset resolution by ID and filename
            by_id = get_audio_asset(aid)
            self.assertIsNotNone(by_id)
            self.assertEqual(by_id["name"], test_audio_name)

            by_fname = get_audio_asset(f"{aid}.wav")
            self.assertIsNotNone(by_fname)
            self.assertEqual(by_fname["id"], aid)
        finally:
            delete_audio_asset(aid)
            update_settings({"default_audio_id": "16cf3bdb-54e6-47e4-bd78-55fce499b6ef"})

if __name__ == "__main__":
    unittest.main()

