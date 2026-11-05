"""
Audio Manager Module for FarmCalling.
Handles storing, converting, and retrieving uploaded and recorded audio files.
"""

import os
import wave
import uuid
import logging
from typing import Optional, Dict, Any, Tuple
from database import add_audio_asset, get_audio_asset, get_audio_assets, delete_audio_asset

logger = logging.getLogger(__name__)

def get_audio_dir() -> str:
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        d = "/tmp/audio"
    else:
        d = os.path.join(os.path.dirname(__file__), "data", "audio")
    os.makedirs(d, exist_ok=True)
    return d

def get_audio_filepath(filename: str) -> str:
    return os.path.join(get_audio_dir(), filename)

def detect_wav_duration(filepath: str) -> float:
    """Calculates duration of WAV file in seconds."""
    try:
        with wave.open(filepath, 'rb') as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate > 0:
                return round(frames / float(rate), 2)
    except Exception:
        pass
    return 0.0

def save_uploaded_audio(file_name: str, file_bytes: bytes, custom_name: Optional[str] = None) -> str:
    """
    Saves an uploaded audio file (MP3/WAV) to the audio directory and registers it in database.
    """
    ext = os.path.splitext(file_name)[1].lower()
    if not ext:
        ext = ".mp3"
    
    unique_filename = f"{uuid.uuid4().hex}{ext}"
    filepath = get_audio_filepath(unique_filename)

    with open(filepath, "wb") as f:
        f.write(file_bytes)

    file_size = len(file_bytes)
    duration = 0.0
    mime_type = "audio/mpeg" if ext == ".mp3" else "audio/wav"

    if ext == ".wav":
        duration = detect_wav_duration(filepath)

    display_name = custom_name.strip() if custom_name else os.path.splitext(file_name)[0]

    asset_id = add_audio_asset(
        name=display_name,
        filename=unique_filename,
        filepath=filepath,
        mime_type=mime_type,
        source_type="upload",
        duration_seconds=duration,
        file_size_bytes=file_size
    )
    logger.info(f"Saved uploaded audio: {unique_filename} (ID: {asset_id})")
    return asset_id

def save_recorded_audio(audio_bytes: bytes, custom_name: Optional[str] = None, format_hint: str = "wav") -> str:
    """
    Saves microphone-recorded audio to the audio directory and registers it.
    """
    ext = f".{format_hint.lower().replace('.', '')}"
    unique_filename = f"rec_{uuid.uuid4().hex}{ext}"
    filepath = get_audio_filepath(unique_filename)

    with open(filepath, "wb") as f:
        f.write(audio_bytes)

    file_size = len(audio_bytes)
    duration = 0.0
    if ext == ".wav":
        duration = detect_wav_duration(filepath)
    
    mime_type = "audio/wav" if ext == ".wav" else "audio/mpeg"
    display_name = custom_name.strip() if custom_name else f"Recorded Audio {unique_filename[:8]}"

    asset_id = add_audio_asset(
        name=display_name,
        filename=unique_filename,
        filepath=filepath,
        mime_type=mime_type,
        source_type="recorded",
        duration_seconds=duration,
        file_size_bytes=file_size
    )
    logger.info(f"Saved recorded audio: {unique_filename} (ID: {asset_id})")
    return asset_id

def create_tts_asset(name: str, text: str, voice: str = "WOMAN") -> str:
    """
    Registers a virtual TTS audio asset (Vobiz Speak).
    """
    asset_id = add_audio_asset(
        name=name,
        filename="tts_virtual",
        filepath="",
        mime_type="text/plain",
        source_type="tts",
        duration_seconds=0.0,
        file_size_bytes=len(text.encode('utf-8')),
        tts_text=text,
        tts_voice=voice
    )
    return asset_id

def get_asset_url(asset_id: str, base_url: str) -> str:
    """
    Returns public HTTP(S) URL for Vobiz to fetch this audio file.
    """
    clean_base = base_url.rstrip("/")
    return f"{clean_base}/audio/{asset_id}"

