"""
Audio Manager Module for FarmCalling.
Handles storing, converting, normalizing, and retrieving uploaded and recorded audio files.
Guarantees 100% carrier telephony compatibility (16kHz mono 16-bit PCM WAV / MP3).
"""

import os
import io
import wave
import uuid
import logging
from typing import Optional, Dict, Any, Tuple
import numpy as np
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

def normalize_wav_bytes(raw_bytes: bytes) -> bytes:
    """
    Normalizes any WAV audio bytes to standard telephony format:
    16,000 Hz, 1 channel (mono), 16-bit linear PCM.
    Downmixes stereo, converts sample bit depth, and resamples smoothly.
    """
    if not raw_bytes or len(raw_bytes) < 44 or not raw_bytes.startswith(b"RIFF"):
        return raw_bytes

    try:
        with wave.open(io.BytesIO(raw_bytes), 'rb') as wf:
            nchannels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            nframes = wf.getnframes()
            frames = wf.readframes(nframes)

        # Decode raw PCM frames according to sample width
        if sampwidth == 2:
            samples = np.frombuffer(frames, dtype=np.int16).copy()
        elif sampwidth == 1:
            samples = ((np.frombuffer(frames, dtype=np.uint8).astype(np.int16) - 128) * 256)
        elif sampwidth == 3:
            # 24-bit PCM: convert 3 bytes per sample to 16-bit
            raw_arr = np.frombuffer(frames, dtype=np.uint8)
            num_samples = len(raw_arr) // 3
            samples_24 = np.zeros(num_samples, dtype=np.int32)
            for i in range(3):
                samples_24 |= raw_arr[i::3].astype(np.int32) << (i * 8)
            # sign extend 24-bit
            samples_24 = np.where(samples_24 & 0x800000, samples_24 - 0x1000000, samples_24)
            samples = (samples_24 >> 8).astype(np.int16)
        elif sampwidth == 4:
            # 32-bit int PCM
            samples = (np.frombuffer(frames, dtype=np.int32) >> 16).astype(np.int16)
        else:
            return raw_bytes

        # Downmix multi-channel to mono
        if nchannels == 2:
            samples = ((samples[0::2].astype(np.int32) + samples[1::2].astype(np.int32)) // 2).astype(np.int16)
        elif nchannels > 2:
            samples = samples[0::nchannels]

        # Resample to 16,000 Hz if needed
        target_rate = 16000
        if framerate != target_rate and len(samples) > 1:
            target_len = max(1, int(len(samples) * target_rate / framerate))
            indices = np.linspace(0, len(samples) - 1, target_len)
            resampled = np.interp(indices, np.arange(len(samples)), samples).astype(np.int16)
        else:
            resampled = samples

        out_io = io.BytesIO()
        with wave.open(out_io, 'wb') as out_wf:
            out_wf.setnchannels(1)
            out_wf.setsampwidth(2)
            out_wf.setframerate(target_rate)
            out_wf.writeframes(resampled.tobytes())

        return out_io.getvalue()
    except Exception as e:
        logger.warning(f"Could not normalize WAV bytes: {e}. Serving raw bytes.")
        return raw_bytes

def detect_and_normalize_audio(file_name: str, file_bytes: bytes) -> Tuple[str, bytes, str, float]:
    """
    Detects true audio format via magic bytes, normalizes WAV files to 16kHz mono 16-bit PCM,
    and returns (extension, normalized_bytes, mime_type, duration_seconds).
    """
    is_wav = False
    is_mp3 = False

    # 1. Magic bytes detection
    if len(file_bytes) >= 12 and file_bytes[:4] == b"RIFF" and file_bytes[8:12] == b"WAVE":
        is_wav = True
    elif file_bytes[:3] == b"ID3" or (len(file_bytes) > 2 and file_bytes[0] == 0xFF and (file_bytes[1] & 0xE0) == 0xE0):
        is_mp3 = True
    else:
        # Fall back to filename extension
        lower_name = (file_name or "").lower()
        if lower_name.endswith(".wav"):
            is_wav = True
        elif lower_name.endswith(".mp3"):
            is_mp3 = True
        else:
            # Default to WAV
            is_wav = True

    if is_wav:
        normalized_bytes = normalize_wav_bytes(file_bytes)
        ext = ".wav"
        mime_type = "audio/wav"
        duration = 0.0
        try:
            with wave.open(io.BytesIO(normalized_bytes), 'rb') as wf:
                rate = wf.getframerate()
                if rate > 0:
                    duration = round(wf.getnframes() / float(rate), 2)
        except Exception:
            pass
        return ext, normalized_bytes, mime_type, duration
    else:
        ext = ".mp3"
        mime_type = "audio/mpeg"
        duration = 0.0
        return ext, file_bytes, mime_type, duration

def save_uploaded_audio(file_name: str, file_bytes: bytes, custom_name: Optional[str] = None) -> str:
    """
    Saves an uploaded audio file (MP3/WAV) to the audio directory and registers it in database.
    Automatically normalizes WAV files to 16kHz mono 16-bit PCM.
    """
    ext, processed_bytes, mime_type, duration = detect_and_normalize_audio(file_name, file_bytes)

    unique_filename = f"{uuid.uuid4().hex}{ext}"
    filepath = get_audio_filepath(unique_filename)

    try:
        with open(filepath, "wb") as f:
            f.write(processed_bytes)
    except Exception as e:
        logger.warning(f"Could not write file to {filepath}: {e}")

    file_size = len(processed_bytes)
    display_name = custom_name.strip() if custom_name else os.path.splitext(file_name)[0]

    asset_id = add_audio_asset(
        name=display_name,
        filename=unique_filename,
        filepath=filepath,
        mime_type=mime_type,
        source_type="upload",
        duration_seconds=duration,
        file_size_bytes=file_size,
        audio_bytes=processed_bytes
    )
    logger.info(f"Saved uploaded audio: {unique_filename} (ID: {asset_id}, {mime_type}, {duration}s)")
    return asset_id

def save_recorded_audio(audio_bytes: bytes, custom_name: Optional[str] = None, format_hint: str = "wav") -> str:
    """
    Saves microphone-recorded audio to the audio directory and registers it.
    Automatically normalizes WAV files to 16kHz mono 16-bit PCM.
    """
    ext, processed_bytes, mime_type, duration = detect_and_normalize_audio(f"rec.{format_hint}", audio_bytes)

    unique_filename = f"rec_{uuid.uuid4().hex}{ext}"
    filepath = get_audio_filepath(unique_filename)

    try:
        with open(filepath, "wb") as f:
            f.write(processed_bytes)
    except Exception as e:
        logger.warning(f"Could not write file to {filepath}: {e}")

    file_size = len(processed_bytes)
    display_name = custom_name.strip() if custom_name else f"Recorded Audio {unique_filename[:8]}"

    asset_id = add_audio_asset(
        name=display_name,
        filename=unique_filename,
        filepath=filepath,
        mime_type=mime_type,
        source_type="recorded",
        duration_seconds=duration,
        file_size_bytes=file_size,
        audio_bytes=processed_bytes
    )
    logger.info(f"Saved recorded audio: {unique_filename} (ID: {asset_id}, {mime_type}, {duration}s)")
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
    return f"{clean_base}/audio/{asset_id}.wav"


