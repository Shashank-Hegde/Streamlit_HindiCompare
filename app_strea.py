# app_stre.py
# Streamlit frontend to compare TWO Hindi ASR backends (6004 and 6005)
# Both must expose POST /streamlitTranscribe

import io
import requests
import streamlit as st

# Backend config
BACKEND_HOST = "49.200.100.22"  # your server
BACKENDS = {
    "Model 6004": 6004,
    "Model 6005": 6005,
}
TIMEOUT_SEC = 180

st.set_page_config(page_title="Hindi ASR – Compare 6004 vs 6005", layout="wide")

st.title("Hindi ASR – Compare 6004 vs 6005")

st.caption(
    "Audio is recorded once in the browser and uploaded to "
    f"**http://{BACKEND_HOST}:6004/streamlitTranscribe** and "
    f"**http://{BACKEND_HOST}:6005/streamlitTranscribe**.  \n"
    "Each backend handles VAD, ASR and translation independently."
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
st.subheader("2. Send to BOTH backends and view outputs")

# Session state for storing results from each model
if "results" not in st.session_state:
    st.session_state["results"] = {}

if st.button("Send to models 6004 & 6005", type="primary"):
    results = {}
    for model_name, port in BACKENDS.items():
        url = f"http://{BACKEND_HOST}:{port}/streamlitTranscribe"
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
                results[model_name] = {
                    "error": f"HTTP {resp.status_code}: {resp.text}"
                }
            else:
                results[model_name] = resp.json()
        except Exception as e:
            results[model_name] = {"error": str(e)}

    st.session_state["results"] = results

st.markdown("---")
st.subheader("3. Outputs (side-by-side)")

results = st.session_state.get("results", {})

if not results:
    st.info("Click **Send to models 6004 & 6005** to run inference.")
    st.stop()

# Two columns: left = 6004, right = 6005
col_left, col_right = st.columns(2)
cols = [col_left, col_right]

for (model_name, result), col in zip(results.items(), cols):
    with col:
        st.markdown(f"### {model_name}")

        if "error" in result:
            st.error(f"Request failed:\n\n`{result['error']}`")
            continue

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
