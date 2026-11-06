"""
Comprehensive Unit and Integration Tests for FarmCalling.
"""

import unittest
import os
os.environ["USE_SQLITE"] = "true"
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
        self.assertTrue(res.content.startswith(b"RIFF"))
        self.assertIn(b"WAVEfmt ", res.content)

        # 2a. Test audio serving with .wav extension
        res_ext = self.client.get(f"/audio/{asset_id}.wav")
        self.assertEqual(res_ext.status_code, 200)
        self.assertEqual(res_ext.headers.get("content-type"), "audio/wav")
        self.assertEqual(res_ext.content, res.content)

        # 2b. Test bundled static audio and HEAD request
        head_res = self.client.head(f"/audio/{asset_id}")
        self.assertEqual(head_res.status_code, 200)

        t1_res = self.client.get("/audio/test1.wav")
        self.assertEqual(t1_res.status_code, 200)
        self.assertEqual(t1_res.headers.get("content-type"), "audio/wav")

        # 2c. Test fallback resilience (never 404 on live call)
        fallback_res = self.client.get("/audio/unknown_missing_audio_id")
        self.assertEqual(fallback_res.status_code, 200)
        self.assertEqual(fallback_res.headers.get("content-type"), "audio/wav")

        # 2d. Test 48kHz WAV normalization to 16kHz
        import wave, io
        wav_48k_io = io.BytesIO()
        with wave.open(wav_48k_io, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(48000)
            wf.writeframes(b"\x00\x00" * 480) # 480 frames at 48kHz = 10ms
        wav_48k_bytes = wav_48k_io.getvalue()
        aid_48k = save_uploaded_audio("high_res_motor.wav", wav_48k_bytes, "Motor Start 48k")
        res_48k = self.client.get(f"/audio/{aid_48k}.wav")
        self.assertEqual(res_48k.status_code, 200)
        self.assertEqual(res_48k.headers.get("content-type"), "audio/wav")
        with wave.open(io.BytesIO(res_48k.content), "rb") as check_wf:
            self.assertEqual(check_wf.getframerate(), 16000)
            self.assertEqual(check_wf.getnchannels(), 1)
            self.assertEqual(check_wf.getsampwidth(), 2)

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
        # 1. Simulate Answer Webhook with loop count = 3
        ans_resp = self.client.post(
            f"/webhook/answer?schedule_id={sched_id}&audio_id={aid}&loop=3",
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
        self.assertIn('loop="3"', ans_resp.text)
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

    def test_07_env_settings_and_api(self):
        from database import is_vobiz_env_configured, is_setting_env_managed, get_env_managed_keys
        
        # 1. Set environment variables
        os.environ["VOBIZ_AUTH_ID"] = "MA_TEST_ENV_999"
        os.environ["VOBIZ_AUTH_TOKEN"] = "secret_env_token_888"
        os.environ["VOBIZ_CALLER_ID"] = "+919876543210"

        try:
            # 2. Verify helper functions
            self.assertTrue(is_vobiz_env_configured())
            self.assertTrue(is_setting_env_managed("auth_id"))
            self.assertTrue(is_setting_env_managed("auth_token"))
            self.assertTrue(is_setting_env_managed("caller_id"))
            self.assertIn("auth_id", get_env_managed_keys())

            # 3. Verify get_settings overrides database
            settings = get_settings()
            self.assertEqual(settings.get("auth_id"), "MA_TEST_ENV_999")
            self.assertEqual(settings.get("auth_token"), "secret_env_token_888")
            self.assertEqual(settings.get("caller_id"), "+919876543210")

            # 4. Verify API response masks token and flags production env
            res = self.client.get("/api/settings")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertTrue(data.get("_is_production_env"))
            self.assertEqual(data.get("auth_id"), "MA_TEST_ENV_999")
            self.assertEqual(data.get("auth_token"), "••••••••••••••••")
            self.assertIn("auth_id", data.get("_env_managed_keys", []))

            # 5. Verify update_settings skips overwriting env-managed keys
            update_settings({
                "auth_id": "SHOULD_BE_IGNORED",
                "test_key_custom": "custom_value_ok"
            })
            self.assertEqual(get_settings().get("auth_id"), "MA_TEST_ENV_999")
            self.assertEqual(get_settings().get("test_key_custom"), "custom_value_ok")

        finally:
            # Clean up test env vars
            if "VOBIZ_AUTH_ID" in os.environ:
                del os.environ["VOBIZ_AUTH_ID"]
            if "VOBIZ_AUTH_TOKEN" in os.environ:
                del os.environ["VOBIZ_AUTH_TOKEN"]
            if "VOBIZ_CALLER_ID" in os.environ:
                del os.environ["VOBIZ_CALLER_ID"]

    def test_08_repeat_count_and_dynamic_audio_normalization(self):
        import wave, io

        # 1. Test uploading a 48kHz WAV audio with NO extension in filename
        raw_48k_io = io.BytesIO()
        with wave.open(raw_48k_io, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(48000)
            wf.writeframes(b"\x10\x00" * 480) # 480 samples
        raw_48k_bytes = raw_48k_io.getvalue()

        # Upload without extension, e.g. "motorstart1"
        aid = save_uploaded_audio("motorstart1", raw_48k_bytes, "Motor Start Pump 1")
        asset = get_audio_asset(aid)

        # Magic bytes detection must correctly identify as WAV and normalize to 16kHz
        self.assertEqual(asset["mime_type"], "audio/wav")
        self.assertTrue(asset["filename"].endswith(".wav"))

        # Verify serving both with and without .wav extension
        res_plain = self.client.get(f"/audio/{aid}")
        self.assertEqual(res_plain.status_code, 200)
        self.assertEqual(res_plain.headers.get("content-type"), "audio/wav")

        res_ext = self.client.get(f"/audio/{aid}.wav")
        self.assertEqual(res_ext.status_code, 200)
        self.assertEqual(res_ext.headers.get("content-type"), "audio/wav")
        self.assertEqual(res_plain.content, res_ext.content)

        # Verify normalized audio is 16kHz mono 16-bit
        with wave.open(io.BytesIO(res_plain.content), "rb") as check_wf:
            self.assertEqual(check_wf.getframerate(), 16000)
            self.assertEqual(check_wf.getnchannels(), 1)
            self.assertEqual(check_wf.getsampwidth(), 2)

        # 2. Test Create Schedule API with repeat count (loop_count = 4)
        sched_res = self.client.post("/api/schedules", json={
            "name": "Evening Motor Alert",
            "to_number": "+919876543210",
            "schedule_type": "once",
            "scheduled_datetime": (datetime.now() + timedelta(hours=2)).isoformat(),
            "audio_id": aid,
            "loop_count": 4
        })
        self.assertEqual(sched_res.status_code, 200)
        sched_id = sched_res.json()["schedule_id"]

        schedule = get_schedule(sched_id)
        self.assertEqual(schedule["loop_count"], 4)

        # 3. Test Answer Webhook automatically reads loop_count from schedule
        ans_resp = self.client.get(f"/webhook/answer?schedule_id={sched_id}&audio_id={aid}")
        self.assertEqual(ans_resp.status_code, 200)
        self.assertIn('loop="4"', ans_resp.text)
        self.assertIn(f"/audio/{aid}.wav", ans_resp.text)
        self.assertIn("<Hangup/>", ans_resp.text)

        # 4. Test Instant Call API with custom repeat count (loop_count = 3)
        # Even if unconfigured, it should process payload and attempt dialing
        inst_res = self.client.post("/api/calls/instant", json={
            "to_number": "+919876543210",
            "audio_id": aid,
            "loop_count": 3
        })
        self.assertEqual(inst_res.status_code, 200)

if __name__ == "__main__":
    unittest.main()

