"""
Audio Studio Page: Record via Microphone, Upload MP3/WAV, or Generate TTS Prompts.
"""

import streamlit as st
import os
from datetime import datetime

from audio_manager import (
    save_uploaded_audio,
    save_recorded_audio,
    create_tts_asset,
    get_audio_assets,
    delete_audio_asset,
    get_asset_url
)
from database import get_settings, update_settings

st.title("🎙️ Audio Studio & Voice Library")
st.caption("Record custom voice announcements from your microphone, upload audio tracks, or configure Text-to-Speech.")

settings = get_settings()
base_url = settings.get("webhook_base_url", "https://api.example.com")
default_audio_id = settings.get("default_audio_id", "")

tab_rec, tab_up, tab_tts = st.tabs(["🎤 Record Microphone", "📁 Upload Audio File", "🗣️ Text-to-Speech (TTS)"])

# TAB 1: Record Microphone
with tab_rec:
    st.subheader("Record Voice Prompt using Microphone")
    st.markdown("Click the microphone button below to record your voice message directly in the browser.")

    rec_name = st.text_input("Recording Name", placeholder="e.g. Cold Wave Alert for Vegetables", key="rec_name_input")
    audio_record = st.audio_input("Record your voice prompt")

    if audio_record is not None:
        st.write("🎧 Preview your recording:")
        st.audio(audio_record)

        if st.button("💾 Save Recording to Audio Library", type="primary", key="save_rec_btn"):
            audio_bytes = audio_record.read()
            if not rec_name.strip():
                rec_name = f"Voice Recording {datetime.now().strftime('%b %d %H:%M')}"
            
            asset_id = save_recorded_audio(audio_bytes=audio_bytes, custom_name=rec_name, format_hint="wav")
            st.success(f"Recording '{rec_name}' saved to Audio Library! (ID: {asset_id[:8]}...)")
            st.rerun()

# TAB 2: Upload Audio File
with tab_up:
    st.subheader("Upload Pre-Recorded Audio File")
    st.markdown("Upload standard **MP3** or **WAV** telephony audio files. Mono 8kHz / 16kHz audio recommended.")

    custom_name = st.text_input("Audio Clip Label", placeholder="e.g. Fertilizer Subsidy Broadcast", key="upload_name_input")
    uploaded_file = st.file_uploader("Choose an audio file", type=["mp3", "wav"], key="uploader_widget")

    if uploaded_file is not None:
        st.write("🎧 Audio Preview:")
        st.audio(uploaded_file)

        if st.button("💾 Save Audio to Library", type="primary", key="save_up_btn"):
            file_bytes = uploaded_file.read()
            c_name = custom_name.strip() if custom_name.strip() else uploaded_file.name
            asset_id = save_uploaded_audio(
                file_name=uploaded_file.name,
                file_bytes=file_bytes,
                custom_name=c_name
            )
            st.success(f"Audio '{c_name}' uploaded and ready for broadcast! (ID: {asset_id[:8]}...)")
            st.rerun()

# TAB 3: Text-to-Speech Studio
with tab_tts:
    st.subheader("Text-to-Speech (TTS) Synthesizer")
    st.markdown("Vobiz natively converts text to voice inside the phone call using `<Speak>` XML verbs.")

    tts_label = st.text_input("TTS Preset Label", placeholder="e.g. Daily Market Price Alert", key="tts_label_input")
    col_v, col_l = st.columns(2)
    with col_v:
        tts_voice = st.selectbox("Voice Tone", ["WOMAN", "MAN"], index=0)
    with col_l:
        tts_lang = st.selectbox("Language / Accent", ["en-US", "en-IN", "hi-IN", "en-GB"], index=1)

    tts_content = st.text_area(
        "Voice Script Text",
        value="Attention all farmers: Today's wholesale market price for tomatoes is 25 rupees per kilogram. Thank you and have a great harvest.",
        height=100
    )

    with st.expander("🔍 View Generated VobizXML"):
        st.code(f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Speak voice="{tts_voice}" language="{tts_lang}">{tts_content}</Speak>
    <Hangup/>
</Response>""", language="xml")

    if st.button("💾 Save TTS Template to Library", type="primary", key="save_tts_btn"):
        if not tts_content.strip():
            st.error("Please enter a voice script.")
        else:
            t_name = tts_label.strip() if tts_label.strip() else f"TTS {tts_voice} ({tts_lang})"
            asset_id = create_tts_asset(name=t_name, text=tts_content.strip(), voice=tts_voice)
            st.success(f"TTS Template '{t_name}' saved to library!")
            st.rerun()

# Section 4: Audio Library & Player
st.markdown("---")
st.subheader("📚 Saved Voice Library")

assets = get_audio_assets()

if not assets:
    st.info("No audio tracks in your library yet. Record or upload one above.")
else:
    for asset in assets:
        with st.container(border=True):
            col_info, col_player, col_actions = st.columns([1.5, 2, 1.2])

            with col_info:
                st.markdown(f"**{asset['name']}**")
                is_default = (asset["id"] == default_audio_id)
                if is_default:
                    st.caption("⭐ **System Default Audio**")
                
                size_kb = round(asset.get("file_size_bytes", 0) / 1024, 1)
                st.caption(f"Source: `{asset['source_type'].upper()}` | Size: `{size_kb} KB` | Format: `{asset['mime_type']}`")
                if asset.get("duration_seconds", 0) > 0:
                    st.caption(f"Duration: `{asset['duration_seconds']}s`")

            with col_player:
                if asset["source_type"] == "tts":
                    st.markdown(f"🗣️ *\"{asset.get('tts_text', '')}\"*")
                elif os.path.exists(asset.get("filepath", "")):
                    st.audio(asset["filepath"])
                    pub_url = get_asset_url(asset["id"], base_url)
                    st.caption(f"Vobiz Stream URL: `{pub_url}`")
                else:
                    st.caption("⚠️ Audio file not found on local disk.")

            with col_actions:
                if not is_default:
                    if st.button("⭐ Set Default", key=f"def_{asset['id']}"):
                        update_settings({"default_audio_id": asset["id"]})
                        st.success("Set as default audio!")
                        st.rerun()
                
                if st.button("🗑️ Delete", key=f"del_aud_{asset['id']}"):
                    delete_audio_asset(asset["id"])
                    if is_default:
                        update_settings({"default_audio_id": ""})
                    st.success("Audio deleted.")
                    st.rerun()

