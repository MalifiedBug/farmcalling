"""
Comprehensive Unit and Integration Tests for FarmCalling.
"""

import unittest
import os
import json
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from database import (
    init_db,
    get_settings,
    update_settings,
    add_audio_asset,
    get_audio_assets,
    get_audio_asset,
    delete_audio_asset,
    create_schedule,
    get_schedules,
    get_schedule,
    update_schedule_status,
    delete_schedule,
    create_call_log,
    update_call_log,
    update_call_log_by_uuid,
    get_call_logs,
    get_call_stats
)
from audio_manager import save_uploaded_audio, save_recorded_audio, create_tts_asset, get_asset_url
from vobiz_client import VobizClient
from server import app as fastapi_app
from scheduler import register_schedule_job, get_scheduler

class TestFarmCalling(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(fastapi_app)

    def test_01_settings(self):
        update_settings({
            "test_key": "test_val",
            "ring_timeout": "45"
        })
        settings = get_settings()
        self.assertEqual(settings.get("test_key"), "test_val")
        self.assertEqual(settings.get("ring_timeout"), "45")

    def test_02_audio_manager_and_serving(self):
        # 1. Save dummy WAV audio
        sample_wav_bytes = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
        asset_id = save_recorded_audio(sample_wav_bytes, custom_name="Test Morning Bell", format_hint="wav")
        self.assertIsNotNone(asset_id)

        asset = get_audio_asset(asset_id)
        self.assertEqual(asset["name"], "Test Morning Bell")
        self.assertEqual(asset["mime_type"], "audio/wav")

        # 2. Test audio serving endpoint in FastAPI
        res = self.client.get(f"/audio/{asset_id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("content-type"), "audio/wav")
        self.assertEqual(res.content, sample_wav_bytes)

        # 3. Test TTS asset
        tts_id = create_tts_asset("Test TTS", "Hello farmer", voice="WOMAN")
        tts_asset = get_audio_asset(tts_id)
        self.assertEqual(tts_asset["source_type"], "tts")
        self.assertEqual(tts_asset["tts_text"], "Hello farmer")

    def test_03_vobiz_xml_generation(self):
        # Test Play XML
        play_xml = VobizClient.generate_play_xml("https://example.com/audio/sample.mp3", loop=2)
        self.assertIn("<Response>", play_xml)
        self.assertIn('<Play loop="2">https://example.com/audio/sample.mp3</Play>', play_xml)
        self.assertIn("<Hangup/>", play_xml)

        # Test Speak XML
        speak_xml = VobizClient.generate_speak_xml("Irrigation Alert", voice="MAN", language="en-IN")
        self.assertIn("<Response>", speak_xml)
        self.assertIn('<Speak voice="MAN" language="en-IN" loop="1">Irrigation Alert</Speak>', speak_xml)
        self.assertIn("<Hangup/>", speak_xml)

    def test_04_webhooks_flow(self):
        # Create audio asset
        sample_wav_bytes = b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
        aid = save_uploaded_audio("alert.wav", sample_wav_bytes, "Irrigation Audio")

        # Create schedule
        sched_id = create_schedule(
            name="Daily Irrigation",
            to_number="+919876543210",
            schedule_type="once",
            scheduled_datetime=(datetime.now() + timedelta(hours=1)).isoformat(),
            audio_id=aid,
            loop_count=1
        )

        call_uuid = "vobiz-test-uuid-999"
        # 1. Simulate Answer Webhook
        ans_resp = self.client.post(
            f"/webhook/answer?schedule_id={sched_id}&audio_id={aid}",
            data={
                "CallUUID": call_uuid,
                "From": "+14155551234",
                "To": "+919876543210",
                "Direction": "outbound"
            }
        )
        self.assertEqual(ans_resp.status_code, 200)
        self.assertIn("application/xml", ans_resp.headers.get("content-type", ""))
        self.assertIn(f"/audio/{aid}", ans_resp.text)
        self.assertIn("<Hangup/>", ans_resp.text)

        # 2. Simulate Hangup Webhook
        hang_resp = self.client.post(
            "/webhook/hangup",
            data={
                "CallUUID": call_uuid,
                "Duration": "42",
                "HangupCause": "NORMAL_CLEARING"
            }
        )
        self.assertEqual(hang_resp.status_code, 200)
        self.assertEqual(hang_resp.json().get("status"), "acknowledged")

    def test_05_schedules_crud_and_registration(self):
        sched_id = create_schedule(
            name="Crop Spray Reminder",
            to_number="+919999988888",
            schedule_type="interval",
            interval_value=45,
            interval_unit="minutes"
        )
        self.assertIsNotNone(sched_id)

        sched = get_schedule(sched_id)
        self.assertEqual(sched["interval_value"], 45)
        self.assertEqual(sched["interval_unit"], "minutes")

        # Register in scheduler
        register_schedule_job(sched_id)
        job = get_scheduler().get_job(sched_id)
        self.assertIsNotNone(job)

        # Pause
        update_schedule_status(sched_id, "paused")
        sched_paused = get_schedule(sched_id)
        self.assertEqual(sched_paused["status"], "paused")

        # Delete
        delete_schedule(sched_id)
        self.assertIsNone(get_schedule(sched_id))

    def test_06_call_stats(self):
        stats = get_call_stats()
        self.assertIn("total_calls", stats)
        self.assertIn("completed_calls", stats)
        self.assertIn("active_schedules", stats)

if __name__ == "__main__":
    unittest.main()

