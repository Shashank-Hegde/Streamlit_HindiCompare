import json
import time
from datetime import datetime

import requests
import streamlit as st

st.set_page_config(page_title="O-Health Transcribe", layout="wide")
st.title("O-Health Transcribe (Upload / Record)")

# =========================
# Config
# =========================
DEFAULT_BACKEND_HOST = "49.200.100.22"
DEFAULT_PORT = 6005
API_PATH = "/streamlitTranscribe"

# =========================
# Sidebar
# =========================
with st.sidebar:
    st.header("Backend")
    backend_host = st.text_input("Host", value=DEFAULT_BACKEND_HOST)
    port = st.number_input("Port", min_value=1, max_value=65535, value=DEFAULT_PORT, step=1)
    timeout_sec = st.number_input("Timeout (sec)", min_value=5, max_value=600, value=120, step=5)

    st.divider()
    st.header("Flags (optional)")
    enable_hindi_correction = st.checkbox("enable_hindi_correction", value=True)
    enable_english_translation = st.checkbox("enable_english_translation", value=True)
    enable_ooc = st.checkbox("enable_ooc", value=True)
    use_condensed_ooc = st.checkbox("use_condensed_ooc", value=True)
    filler_threshold = st.slider("filler_threshold", 0.0, 1.0, 0.75, 0.01)
    medical_threshold = st.slider("medical_threshold", 0.0, 1.0, 0.70, 0.01)

    st.divider()
    st.header("VAD thresholds")
    panns_threshold = st.slider("panns_threshold", 0.0, 1.0, 0.20, 0.01)
    vad_threshold = st.slider("vad_threshold", 0.0, 1.0, 0.20, 0.01)

    st.divider()
    st.header("Debug display")
    show_raw = st.checkbox("Show raw response text", value=True)
    show_headers = st.checkbox("Show response headers", value=False)

st.caption(f"Target: http://{backend_host}:{port}{API_PATH}")

# =========================
# Input method
# =========================
input_method = st.radio(
    "Choose input method",
    ["Upload WAV file", "Record with microphone (experimental)"],
    index=0,
    key="input_method",
)

audio_bytes = None
audio_name = None

if input_method == "Upload WAV file":
    uploaded = st.file_uploader("Upload .wav", type=["wav"], key="uploader")
    if uploaded is not None:
        audio_bytes = uploaded.read()
        audio_name = uploaded.name

else:
    st.info(
        "If recording widget becomes unresponsive, switch back to Upload WAV. "
        "Browser mic permission/state can sometimes break Streamlit audio_input."
    )
    try:
        rec = st.audio_input("Record audio", key="recorder")
        if rec is not None:
            audio_bytes = rec.getvalue()
            audio_name = f"recording_{datetime.utcnow().strftime('%Y-%m-%dT%H-%M-%S-%fZ')}.wav"
    except Exception as e:
        st.error(f"Audio recorder error: {e}")

if audio_bytes and audio_name:
    st.success(f"Audio ready: {audio_name} ({len(audio_bytes)} bytes)")
    st.audio(audio_bytes, format="audio/wav")

st.divider()

# =========================
# Call backend
# =========================
def do_request():
    url = f"http://{backend_host}:{port}{API_PATH}"

    files = {"file": (audio_name, audio_bytes, "audio/wav")}
    data = {
        # keep these because your backend might use them
        "client_filename": audio_name,
        "panns_threshold": str(panns_threshold),
        "vad_threshold": str(vad_threshold),
        "enable_hindi_correction": "true" if enable_hindi_correction else "false",
        "enable_english_translation": "true" if enable_english_translation else "false",
        "enable_ooc": "true" if enable_ooc else "false",
        "filler_threshold": str(filler_threshold),
        "medical_threshold": str(medical_threshold),
        "use_condensed_ooc": "true" if use_condensed_ooc else "false",
    }

    t0 = time.perf_counter()
    resp = requests.post(url, files=files, data=data, timeout=timeout_sec)
    dt = time.perf_counter() - t0
    return resp, dt

run = st.button("Transcribe", type="primary", use_container_width=True)

if run:
    if not audio_bytes or not audio_name:
        st.warning("Please upload/record a WAV first.")
    else:
        with st.spinner("Calling backend..."):
            try:
                resp, elapsed = do_request()
            except requests.exceptions.RequestException as e:
                st.error(f"Request failed: {type(e).__name__}: {e}")
                st.stop()

        # ALWAYS show status + elapsed (even if JSON parse fails)
        st.subheader("HTTP Result")
        st.write("Status:", resp.status_code)
        st.write("Elapsed (sec):", round(elapsed, 3))

        if show_headers:
            st.write("Headers:")
            st.json(dict(resp.headers))

        if show_raw:
            st.subheader("Raw Response (first 4000 chars)")
            st.code(resp.text[:4000])

        # Parse JSON safely
        st.subheader("Parsed JSON")
        try:
            payload = resp.json()
            st.json(payload)

            # Pull common fields if present
            st.subheader("Key Outputs")
            st.write("file:", payload.get("file", ""))
            st.write("audio_duration_seconds:", payload.get("audio_duration_seconds", ""))
            st.write("raw_hindi:", payload.get("raw_hindi", payload.get("raw_transcription", "")))
            st.write("corrected_hindi:", payload.get("corrected_hindi", ""))
            st.write("english_translation:", payload.get("english_translation", payload.get("transcription", "")))

        except Exception as e:
            st.error(f"JSON parse failed: {e}")
            st.write("If backend returned non-JSON, check the raw response above.")
