import io
import time
import os
import tempfile
from datetime import datetime

import requests
import streamlit as st

BACKEND_HOST = "127.0.0.1"
PORT = 6004
TIMEOUT_SEC = 180
VOICE_REQUEST_DIR = "/home/oobadmin/nodejs_final/data/voice_request_files"

st.set_page_config(page_title="English ASR – Port 6004", layout="centered")
st.title("🎙️ English ASR – Port 6004")
st.caption("Whisper Large V3 — speak in English")
st.markdown("---")

# -------------------- Audio input (record or upload) --------------------

st.subheader("1. Provide English audio")

input_method = st.radio(
    "Choose input method:",
    ["Record with microphone", "Upload audio file"],
    index=0,
    key="audio_input_method",
)

audio_bytes = None
upload_name = "recording.wav"

if input_method == "Record with microphone":
    audio_file = st.audio_input(
        "Click to record, then click again to stop:",
        key="audio_rec",
    )
    if audio_file is not None:
        audio_bytes = audio_file.getvalue()

else:
    uploaded_file = st.file_uploader(
        "Upload an audio file:",
        type=["wav", "mp3", "m4a", "ogg", "webm"],
        key="audio_upload",
    )
    if uploaded_file is not None:
        audio_bytes = uploaded_file.read()
        upload_name = uploaded_file.name

if audio_bytes is None:
    st.info("👆 Record or upload audio to begin.")
    st.stop()

st.success("Audio ready.")
st.audio(audio_bytes, format="audio/wav")

st.markdown("---")

# -------------------- VAD threshold --------------------

st.subheader("2. Settings")

vad_threshold = st.slider(
    "VAD / Speech detection threshold (lower = more sensitive)",
    min_value=0.0,
    max_value=1.0,
    value=0.2,
    step=0.01,
)

# -------------------- Send --------------------

st.markdown("---")
st.subheader("3. Run inference")

if "result" not in st.session_state:
    st.session_state["result"] = None

if st.button("▶ Send to model", type="primary"):
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    audio_label = f"streamlit_english_{ts}.wav"
    save_path = os.path.join(VOICE_REQUEST_DIR, audio_label)

    url = f"http://{BACKEND_HOST}:{PORT}/convertSpeechToText"

    with st.spinner(f"Saving audio and sending to port {PORT}…"):
        try:
            # Save audio to VOICE_REQUEST_DIR so backend can find it
            os.makedirs(VOICE_REQUEST_DIR, exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(audio_bytes)

            start_t = time.perf_counter()
            resp = requests.post(
                url,
                json={
                    "audioFileName": audio_label,
                    "panns_threshold": vad_threshold,
                    "vad_threshold": vad_threshold,
                },
                timeout=TIMEOUT_SEC,
            )
            rtt = time.perf_counter() - start_t

            if resp.status_code != 200:
                st.session_state["result"] = {
                    "error": f"HTTP {resp.status_code}: {resp.text}",
                    "rtt_seconds": round(rtt, 3),
                }
            else:
                data = resp.json()
                data["rtt_seconds"] = round(rtt, 3)
                st.session_state["result"] = data

        except Exception as e:
            st.session_state["result"] = {"error": str(e), "rtt_seconds": None}

# -------------------- Show results --------------------

result = st.session_state.get("result")
if not result:
    st.stop()

st.markdown("---")
st.subheader("4. Output")

rtt_val = result.get("rtt_seconds")

# Duration — may be in results[0] or top-level
dur_val = None
results_list = result.get("results", [])
if results_list and isinstance(results_list, list):
    dur_val = results_list[0].get("audio_duration_seconds")

m1, m2 = st.columns(2)
m1.metric("RTT (s)", f"{rtt_val}" if rtt_val is not None else "—")
m2.metric("Audio duration (s)",
          f"{dur_val:.2f}" if isinstance(dur_val, (int, float)) else "—")

if "error" in result:
    st.error(f"Request failed:\n\n`{result['error']}`")
    st.stop()

# Pull from results list if present, else top-level
if results_list:
    r = results_list[0]
    raw_text = r.get("raw_transcription", "N/A")
    eng_text = r.get("english_translation", result.get("transcription", "N/A"))
else:
    raw_text = result.get("raw_transcription", "N/A")
    eng_text = result.get("english_translation", result.get("transcription", "N/A"))

st.markdown("**🔤 Raw transcription:**")
st.code(raw_text, language="text")

st.markdown("**🌐 English (processed):**")
st.code(eng_text, language="text")

with st.expander("Full JSON response"):
    st.json(result)
