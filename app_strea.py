import io
import os
import time
import requests
import streamlit as st

# ----------------- CONFIG -----------------

BACKEND_HOST = "49.200.100.22"
MODEL_PORTS = [6004, 6005]  # FastAPI apps running app.py with /convertSpeechToText

# MUST match VOICE_REQUEST_DIR in app.py
VOICE_REQUEST_DIR = "/home/oobadmin/nodejs_final/data/voice_response_files"

TIMEOUT_SEC = 180

st.set_page_config(page_title="Hindi ASR – Model Compare", layout="wide")

st.title("Hindi ASR – Compare Two Models")

st.caption(
    f"Audio is recorded in the browser, saved on this server under\n"
    f"`{VOICE_REQUEST_DIR}`, then sent to FastAPI apps on "
    f"**{BACKEND_HOST}:6004** and **{BACKEND_HOST}:6005** via "
    "the `/convertSpeechToText` endpoint using `audioFileName`."
)

st.markdown("---")

# -------------------- Audio recording --------------------

st.subheader("1. Record Hindi audio")

audio_file = st.audio_input(
    "Click to record your Hindi audio, then click again to stop:",
    key="audio_rec",
)

if audio_file is None:
    st.info("👆 Record some audio to begin.")
    st.stop()

# Read bytes once
audio_bytes = audio_file.getvalue()
st.success("Audio captured.")
st.audio(audio_bytes, format="audio/wav")

# -------------------- Save on server --------------------

st.markdown("---")
st.subheader("2. Save & send to models")

if "results" not in st.session_state:
    st.session_state["results"] = None
if "saved_filename" not in st.session_state:
    st.session_state["saved_filename"] = None

# Ensure directory exists (Streamlit runs on same server)
os.makedirs(VOICE_REQUEST_DIR, exist_ok=True)

# Generate unique filename
timestamp = int(time.time())
saved_filename = f"streamlit_rec_{timestamp}.wav"
saved_path = os.path.join(VOICE_REQUEST_DIR, saved_filename)

# Save the recorded audio into VOICE_REQUEST_DIR
with open(saved_path, "wb") as f:
    f.write(audio_bytes)

st.info(f"Saved audio on server as:\n`{saved_path}`")
st.session_state["saved_filename"] = saved_filename

col_btn, _ = st.columns([1, 3])

with col_btn:
    if st.button("Send to both models", type="primary"):
        if not st.session_state["saved_filename"]:
            st.error("No saved filename found. Please re-record and try again.")
            st.stop()

        audio_name = st.session_state["saved_filename"]
        results = {}

        for idx, port in enumerate(MODEL_PORTS, start=1):
            model_label = f"Model {idx} (port {port})"
            url = f"http://{BACKEND_HOST}:{port}/convertSpeechToText"

            payload = {
                "audioFileName": audio_name
                # You can also use "audioFiles": [audio_name] if desired
            }

            try:
                resp = requests.post(
                    url,
                    json=payload,
                    timeout=TIMEOUT_SEC,
                )
                if resp.status_code != 200:
                    results[model_label] = {
                        "error": f"HTTP {resp.status_code}: {resp.text}"
                    }
                else:
                    results[model_label] = resp.json()
            except Exception as e:
                results[model_label] = {"error": str(e)}

        st.session_state["results"] = results

# -------------------- Show results --------------------

st.markdown("---")
st.subheader("3. Model Outputs")

results = st.session_state.get("results")
if not results:
    st.info("Run inference first by clicking **Send to both models**.")
    st.stop()

col1, col2 = st.columns(2)
cols = [col1, col2]

for (model_label, result), col in zip(results.items(), cols):
    with col:
        st.markdown(f"### {model_label}")

        if "error" in result:
            st.error(f"Request failed:\n\n`{result['error']}`")
            continue

        # app.py returns:
        # {
        #   "processed_files": N,
        #   "parallel_pipelines": ...,
        #   "results": [
        #       {
        #           "file": "...",
        #           "status": "success",
        #           "audio_duration_seconds": ...,
        #           "speech_probability": ...,
        #           "raw_transcription": "...",
        #           "corrected_hindi": "...",
        #           "english_translation": "..."
        #       }
        #   ],
        #   "transcription": "..."
        # }

        files_results = result.get("results", [])
        if not files_results:
            st.error("Backend returned no `results` field.")
            continue

        item = files_results[0]

        st.markdown(
            f"**File on server:** `{item.get('file', '?')}`  \n"
            f"**Duration (s):** `{item.get('audio_duration_seconds', '?')}`  \n"
            f"**Speech probability:** `{item.get('speech_probability', '?')}`"
        )

        st.markdown("**Hindi (raw transcription):**")
        st.code(item.get("raw_transcription", "N/A"), language="text")

        st.markdown("**Hindi (corrected):**")
        st.code(item.get("corrected_hindi", "N/A"), language="text")

        st.markdown("**English translation:**")
        st.code(item.get("english_translation", "N/A"), language="text")
