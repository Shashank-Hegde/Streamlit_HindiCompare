import json
import time
from datetime import datetime

import requests
import streamlit as st

# =========================
# Streamlit page setup
# =========================
st.set_page_config(page_title="Parallel Transcribe (Upload / Record)", layout="wide")
st.title("Parallel Transcribe (Upload / Record)")

# =========================
# Config
# =========================
BACKEND_HOST = "49.200.100.22"

# IMPORTANT: Only 6005 is alive per your curl output
MODEL_PORTS = [6005]

TIMEOUT_SEC = 120  # keep reasonable; backend is fast per curl

# Endpoint used by Streamlit
API_PATH = "/streamlitTranscribe"

# Where we store basic debug info across reruns
if "last_debug" not in st.session_state:
    st.session_state["last_debug"] = {}

# =========================
# Sidebar controls
# =========================
with st.sidebar:
    st.header("Backend Settings")

    backend_host = st.text_input("Backend host", value=BACKEND_HOST)
    ports_str = st.text_input("Ports (comma-separated)", value=",".join(map(str, MODEL_PORTS)))
    try:
        model_ports = [int(p.strip()) for p in ports_str.split(",") if p.strip()]
        if not model_ports:
            model_ports = [6005]
    except Exception:
        model_ports = [6005]

    timeout_sec = st.number_input("HTTP timeout (seconds)", min_value=5, max_value=600, value=TIMEOUT_SEC, step=5)

    st.divider()
    st.header("Pipeline Flags (match curl)")

    enable_hindi_correction = st.checkbox("enable_hindi_correction", value=True)
    enable_english_translation = st.checkbox("enable_english_translation", value=True)
    enable_ooc = st.checkbox("enable_ooc", value=True)
    use_condensed_ooc = st.checkbox("use_condensed_ooc", value=True)

    filler_threshold = st.slider("filler_threshold", 0.0, 1.0, 0.75, 0.01)
    medical_threshold = st.slider("medical_threshold", 0.0, 1.0, 0.70, 0.01)

    st.divider()
    st.header("VAD/PA-NNS thresholds (if used)")

    panns_threshold = st.slider("panns_threshold", 0.0, 1.0, 0.20, 0.01)
    vad_threshold = st.slider("vad_threshold", 0.0, 1.0, 0.20, 0.01)

    st.divider()
    show_debug = st.checkbox("Show debug", value=True)
    show_raw_response = st.checkbox("Show raw response text", value=False)
    show_mem_logs = st.checkbox("Show mem_logs if present", value=False)

# =========================
# Input selection
# =========================
# IMPORTANT: Default to Upload WAV to avoid st.audio_input freeze issues
input_method = st.radio(
    "Choose input method",
    ["Upload WAV file", "Record with microphone (experimental)"],
    index=0,
)

audio_bytes = None
audio_label = None

if input_method == "Upload WAV file":
    uploaded_file = st.file_uploader("Upload a WAV file", type=["wav"])
    if uploaded_file is not None:
        audio_bytes = uploaded_file.read()
        audio_label = uploaded_file.name

elif input_method == "Record with microphone (experimental)":
    st.info(
        "If this gets stuck on some browsers, switch to 'Upload WAV file'. "
        "Microphone permissions or widget state can cause Streamlit to appear frozen."
    )
    try:
        audio_file = st.audio_input("Record audio")
        if audio_file is not None:
            audio_bytes = audio_file.getvalue()
            # name it with timestamp
            audio_label = f"recording_{datetime.utcnow().strftime('%Y-%m-%dT%H-%M-%S-%fZ')}.wav"
    except Exception as e:
        st.error(f"Audio input widget error: {e}")

# Preview input audio
if audio_bytes and audio_label:
    st.success(f"Audio ready: {audio_label} ({len(audio_bytes)} bytes)")
    st.audio(audio_bytes, format="audio/wav")

st.divider()

# =========================
# Helper: call backend
# =========================
def call_backend(port: int, audio_bytes_local: bytes, filename: str):
    """
    Calls /streamlitTranscribe with multipart upload + form fields.
    Mirrors your working curl flags so behavior is consistent.
    """
    url = f"http://{backend_host}:{port}{API_PATH}"

    # Multipart file field must be named "file"
    files = {
        "file": (filename, audio_bytes_local, "audio/wav"),
    }

    # Form fields (strings are safest for multipart)
    data = {
        "client_filename": filename,
        "panns_threshold": str(panns_threshold),
        "vad_threshold": str(vad_threshold),
        "enable_hindi_correction": "true" if enable_hindi_correction else "false",
        "enable_english_translation": "true" if enable_english_translation else "false",
        "enable_ooc": "true" if enable_ooc else "false",
        "filler_threshold": str(filler_threshold),
        "medical_threshold": str(medical_threshold),
        "use_condensed_ooc": "true" if use_condensed_ooc else "false",
    }

    debug = {"url": url, "port": port, "filename": filename, "req_bytes": len(audio_bytes_local)}

    t0 = time.perf_counter()
    resp = requests.post(url, files=files, data=data, timeout=timeout_sec)
    dt = time.perf_counter() - t0

    debug["elapsed_sec"] = round(dt, 3)
    debug["status_code"] = resp.status_code
    debug["resp_len"] = len(resp.text)

    # Try JSON
    result = None
    json_err = None
    try:
        result = resp.json()
    except Exception as e:
        json_err = str(e)

    debug["json_parse_error"] = json_err
    return resp, result, debug


# =========================
# Run button
# =========================
col_run1, col_run2 = st.columns([1, 2])

with col_run1:
    run = st.button("Send to backend", type="primary", use_container_width=True)

with col_run2:
    st.caption(
        f"Endpoint: http://{BACKEND_HOST}:{MODEL_PORTS[0]}{API_PATH} (configured ports: {model_ports})"
    )

if run:
    if not audio_bytes or not audio_label:
        st.warning("Please upload/record an audio file first.")
    else:
        results = {}
        debug_all = {}

        with st.spinner(f"Calling backend on ports: {model_ports} ..."):
            for idx, port in enumerate(model_ports, start=1):
                model_label = f"Pipeline {idx} (port {port})"
                try:
                    st.write(f"DEBUG: calling {model_label} ...") if show_debug else None
                    resp, parsed, dbg = call_backend(port, audio_bytes, audio_label)
                    debug_all[model_label] = dbg

                    if resp.status_code == 200 and isinstance(parsed, dict):
                        results[model_label] = parsed
                    else:
                        results[model_label] = {
                            "error": True,
                            "status_code": resp.status_code,
                            "text": resp.text[:2000],
                        }

                except requests.exceptions.ConnectTimeout as e:
                    results[model_label] = {"error": True, "exception": f"ConnectTimeout: {e}"}
                except requests.exceptions.ReadTimeout as e:
                    results[model_label] = {"error": True, "exception": f"ReadTimeout: {e}"}
                except requests.exceptions.ConnectionError as e:
                    results[model_label] = {"error": True, "exception": f"ConnectionError: {e}"}
                except Exception as e:
                    results[model_label] = {"error": True, "exception": f"{type(e).__name__}: {e}"}

        st.session_state["last_debug"] = debug_all

        st.success("Done. Results below.")
        st.divider()

        # Render results
        # Use as many columns as ports, up to 3 columns (nice layout)
        ncols = min(max(len(model_ports), 1), 3)
        cols = st.columns(ncols)

        for i, (model_label, payload) in enumerate(results.items()):
            with cols[i % ncols]:
                st.subheader(model_label)

                # Error
                if isinstance(payload, dict) and payload.get("error"):
                    st.error(payload)
                    continue

                # Normal payload
                if isinstance(payload, dict):
                    # Print key fields if present
                    st.write("**file:**", payload.get("file", ""))
                    st.write("**audio_duration_seconds:**", payload.get("audio_duration_seconds", ""))
                    st.write("**raw_hindi:**", payload.get("raw_hindi", payload.get("raw_transcription", "")))
                    st.write("**corrected_hindi:**", payload.get("corrected_hindi", ""))
                    st.write("**english_translation:**", payload.get("english_translation", payload.get("transcription", "")))

                    # Optional: show mem_logs
                    if show_mem_logs:
                        mem_logs = payload.get("mem_logs")
                        if isinstance(mem_logs, list) and mem_logs:
                            st.caption("mem_logs (last 30 lines)")
                            tail = mem_logs[-30:]
                            st.code("\n".join([str(x) for x in tail]))
                        elif mem_logs is not None:
                            st.caption("mem_logs present but not a list")
                            st.write(mem_logs)

                    # Optional: show full JSON
                    with st.expander("Show full JSON"):
                        st.json(payload)
                else:
                    st.write(payload)

        # Debug output
        if show_debug:
            st.divider()
            st.subheader("Debug (request/response timings)")
            st.json(st.session_state["last_debug"])

        if show_raw_response:
            st.divider()
            st.subheader("Raw responses (first 2000 chars)")
            for model_label, dbg in st.session_state["last_debug"].items():
                st.write(model_label, dbg)

st.caption("Tip: If microphone recording appears stuck, use Upload WAV. Backend is confirmed working via curl.")
