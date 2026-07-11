import io
import time
from datetime import datetime

import requests
import streamlit as st

BACKEND_HOST = "49.200.100.22"
PORT = 6004
TIMEOUT_SEC = 180

st.set_page_config(page_title="English ASR – Port 6004", layout="centered")
st.title("🎙️ English ASR – Port 6004")
st.caption("audio in English")
st.markdown("---")

# -------------------- Audio input --------------------

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
    url = f"http://{BACKEND_HOST}:{PORT}/streamlitTranscribe"

    with st.spinner(f"Sending to port {PORT}…"):
        try:
            start_t = time.perf_counter()
            resp = requests.post(
                url,
                data={
                    "client_filename": audio_label,
                    "panns_threshold": vad_threshold,
                    "vad_threshold": vad_threshold,
                },
                files={
                    "file": (upload_name, io.BytesIO(audio_bytes), "audio/wav")
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
dur_val = result.get("audio_duration_seconds")

m1, m2 = st.columns(2)
m1.metric("RTT (s)", f"{rtt_val}" if rtt_val is not None else "—")
m2.metric("Audio duration (s)",
          f"{dur_val:.2f}" if isinstance(dur_val, (int, float)) else "—")

if "error" in result:
    st.error(f"Request failed:\n\n`{result['error']}`")
    st.stop()

st.markdown("**🔤 Raw transcription:**")
st.code(result.get("raw_transcription", "N/A"), language="text")

st.markdown("**🌐 English (processed):**")
st.code(result.get("english_translation", "N/A"), language="text")

with st.expander("Full JSON response"):
    st.json(result)
