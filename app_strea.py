# app.py
# Minimal Streamlit frontend for ONE Hindi ASR backend on port 6004.
# It posts recorded audio to /streamlitTranscribe and shows the JSON.

import io
import requests
import streamlit as st

# Backend config
BACKEND_HOST = "49.200.100.22"  # your server
BACKEND_PORT = 6004
TIMEOUT_SEC = 180

st.set_page_config(page_title="Hindi ASR – Model 6004", layout="wide")

st.title("Hindi ASR – Model 6004")

st.caption(
    f"Audio is recorded in the browser and uploaded directly to "
    f"**http://{BACKEND_HOST}:{BACKEND_PORT}/streamlitTranscribe**. "
    "The backend handles VAD, ASR and translation."
)

st.markdown("---")

# 1. Record audio
st.subheader("1. Record Hindi audio")

audio_file = st.audio_input(
    "Click to start recording, then click again to stop:",
    key="audio_rec",
)

if audio_file is None:
    st.info("👆 Record some audio to begin.")
    st.stop()

audio_bytes = audio_file.getvalue()
st.success("Audio captured.")
st.audio(audio_bytes, format="audio/wav")

st.markdown("---")
st.subheader("2. Send to backend and view outputs")

if "result" not in st.session_state:
    st.session_state["result"] = None

if st.button("Send to model on 6004", type="primary"):
    url = f"http://{BACKEND_HOST}:{BACKEND_PORT}/streamlitTranscribe"
    try:
        resp = requests.post(
            url,
            files={
                "file": (
                    "recording.wav",
                    io.BytesIO(audio_bytes),
                    "audio/wav",
                )
            },
            timeout=TIMEOUT_SEC,
        )
        if resp.status_code != 200:
            st.session_state["result"] = {
                "error": f"HTTP {resp.status_code}: {resp.text}"
            }
        else:
            st.session_state["result"] = resp.json()
    except Exception as e:
        st.session_state["result"] = {"error": str(e)}

st.markdown("---")
st.subheader("3. Output")

result = st.session_state.get("result")
if not result:
    st.info("Click **Send to model on 6004** to run inference.")
    st.stop()

if "error" in result:
    st.error(f"Request failed:\n\n`{result['error']}`")
    st.stop()

# Handle both possible JSON shapes defensively:
raw_hindi = (
    result.get("raw_hindi")
    or result.get("raw_transcription")
    or "N/A"
)
corrected_hindi = result.get("corrected_hindi", "N/A")
english_translation = result.get("english_translation", "N/A")
duration = result.get("audio_duration_seconds", result.get("audio_duration", "N/A"))
speech_prob = result.get("speech_probability", "N/A")
file_name = result.get("file", "N/A")

st.markdown(
    f"**Backend file name:** `{file_name}`  \n"
    f"**Audio duration (s):** `{duration}`  \n"
    f"**Speech probability:** `{speech_prob}`"
)

st.markdown("**Hindi (raw):**")
st.code(raw_hindi, language="text")

st.markdown("**Hindi (corrected):**")
st.code(corrected_hindi, language="text")

st.markdown("**English translation:**")
st.code(english_translation, language="text")
