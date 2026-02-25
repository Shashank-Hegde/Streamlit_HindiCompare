import json
import os
import time
from datetime import datetime

import requests
import streamlit as st

st.set_page_config(page_title="O-Health Transcribe", layout="wide")
st.title("O-Health Transcribe (Upload / Record)")

API_PATH = "/streamlitTranscribe"

# =========================
# Sidebar config
# =========================
with st.sidebar:
    st.header("Backend Target (IMPORTANT)")

    st.markdown(
        """
If Streamlit cannot reach the **public IP**, use:
- **127.0.0.1** if Streamlit + FastAPI are on the same server
- **192.168.x.x** if FastAPI is on your LAN
        """
    )

    # Provide multiple candidates. Streamlit will try them in order.
    # Put the most-likely reachable one first.
    backend_candidates_text = st.text_area(
        "Backend hosts to try (one per line)",
        value="\n".join([
            "127.0.0.1",         # same machine
            "192.168.10.1",      # LAN (based on your logs)
            "49.200.100.22",     # public
        ]),
        height=110
    )

    port = st.number_input("Port", min_value=1, max_value=65535, value=6005, step=1)
    timeout_connect = st.number_input("Connect timeout (sec)", min_value=1, max_value=60, value=5, step=1)
    timeout_read = st.number_input("Read timeout (sec)", min_value=5, max_value=600, value=120, step=5)

    st.divider()
    st.header("Flags (match curl)")
    enable_hindi_correction = st.checkbox("enable_hindi_correction", value=True)
    enable_english_translation = st.checkbox("enable_english_translation", value=True)
    enable_ooc = st.checkbox("enable_ooc", value=True)
    filler_threshold = st.slider("filler_threshold", 0.0, 1.0, 0.75, 0.01)
    medical_threshold = st.slider("medical_threshold", 0.0, 1.0, 0.70, 0.01)
    use_condensed_ooc = st.checkbox("use_condensed_ooc", value=True)

    st.divider()
    st.header("Debug")
    show_raw = st.checkbox("Show raw response", value=True)
    show_headers = st.checkbox("Show response headers", value=False)
    show_attempts = st.checkbox("Show host attempts", value=True)

backend_hosts = [h.strip() for h in backend_candidates_text.splitlines() if h.strip()]

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
        "If mic recording gets stuck, switch back to Upload WAV. "
        "Browser permissions/state can break Streamlit audio_input."
    )
    rec = st.audio_input("Record audio", key="recorder")
    if rec is not None:
        audio_bytes = rec.getvalue()
        audio_name = f"recording_{datetime.utcnow().strftime('%Y-%m-%dT%H-%M-%S-%fZ')}.wav"

if audio_bytes and audio_name:
    st.success(f"Audio ready: {audio_name} ({len(audio_bytes)} bytes)")
    st.audio(audio_bytes, format="audio/wav")

st.divider()

# =========================
# Requests session (disable proxies!)
# =========================
session = requests.Session()
session.trust_env = False  # IMPORTANT: ignore HTTP_PROXY/HTTPS_PROXY env vars

def try_backend(host: str):
    url = f"http://{host}:{port}{API_PATH}"

    files = {"file": (audio_name, audio_bytes, "audio/wav")}
    data = {
        "client_filename": audio_name,
        "enable_hindi_correction": "true" if enable_hindi_correction else "false",
        "enable_english_translation": "true" if enable_english_translation else "false",
        "enable_ooc": "true" if enable_ooc else "false",
        "filler_threshold": str(filler_threshold),
        "medical_threshold": str(medical_threshold),
        "use_condensed_ooc": "true" if use_condensed_ooc else "false",
    }

    t0 = time.perf_counter()
    resp = session.post(
        url,
        files=files,
        data=data,
        timeout=(timeout_connect, timeout_read),  # (connect, read)
    )
    dt = time.perf_counter() - t0
    return url, resp, dt

run = st.button("Transcribe", type="primary", use_container_width=True)

if run:
    if not audio_bytes or not audio_name:
        st.warning("Please upload/record a WAV first.")
        st.stop()

    attempts = []
    last_exc = None

    with st.spinner("Calling backend..."):
        for host in backend_hosts:
            try:
                url, resp, elapsed = try_backend(host)
                attempts.append({"host": host, "url": url, "status": resp.status_code, "elapsed_sec": round(elapsed, 3)})

                st.subheader("HTTP Result")
                st.write("Used URL:", url)
                st.write("Status:", resp.status_code)
                st.write("Elapsed (sec):", round(elapsed, 3))

                if show_headers:
                    st.write("Headers:")
                    st.json(dict(resp.headers))

                if show_raw:
                    st.subheader("Raw Response (first 4000 chars)")
                    st.code(resp.text[:4000])

                st.subheader("Parsed JSON")
                try:
                    payload = resp.json()
                    st.json(payload)
                    st.subheader("Key Outputs")
                    st.write("file:", payload.get("file", ""))
                    st.write("audio_duration_seconds:", payload.get("audio_duration_seconds", ""))
                    st.write("raw_hindi:", payload.get("raw_hindi", payload.get("raw_transcription", "")))
                    st.write("corrected_hindi:", payload.get("corrected_hindi", ""))
                    st.write("english_translation:", payload.get("english_translation", payload.get("transcription", "")))
                except Exception as e:
                    st.error(f"JSON parse failed: {e}")

                # success path: stop trying other hosts
                last_exc = None
                break

            except requests.exceptions.ConnectTimeout as e:
                last_exc = f"ConnectTimeout: {e}"
                attempts.append({"host": host, "error": "ConnectTimeout"})
            except requests.exceptions.ReadTimeout as e:
                last_exc = f"ReadTimeout: {e}"
                attempts.append({"host": host, "error": "ReadTimeout"})
            except requests.exceptions.ConnectionError as e:
                last_exc = f"ConnectionError: {e}"
                attempts.append({"host": host, "error": "ConnectionError"})
            except Exception as e:
                last_exc = f"{type(e).__name__}: {e}"
                attempts.append({"host": host, "error": type(e).__name__})

    if show_attempts:
        st.divider()
        st.subheader("Host Attempts")
        st.json(attempts)

    if last_exc is not None:
        st.error("All backend hosts failed.")
        st.code(last_exc)
        st.info(
            "Fix: Use a backend host reachable from the Streamlit server.\n"
            "If Streamlit runs on the same server as FastAPI, use 127.0.0.1.\n"
            "If it’s on LAN, use the backend’s LAN IP (e.g., 192.168.10.1)."
        )
    
