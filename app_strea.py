#!/usr/bin/env python3
"""
Auto-VAD Hindi ASR — Fixed PoC
================================
Architecture fix: browser sends audio → Streamlit Python → FastAPI backend
This eliminates CORS and mixed-content (HTTP/HTTPS) browser restrictions.

Flow:
  1. Streamlit serves the VAD component (same origin as the app)
  2. JS detects speech, records audio, encodes to base64
  3. JS calls Streamlit.setComponentValue({audio_b64, mime_type, filename})
  4. Python receives it, decodes bytes, POSTs to FastAPI via `requests`
  5. Results displayed in Streamlit — no browser network call to FastAPI at all

Run:
  streamlit run streamlit_vad_poc.py
"""

import base64
import io
import json
import time
from datetime import datetime
from pathlib import Path

import requests
import streamlit as st
import streamlit.components.v1 as components

# ──────────────────────────────────────────────────────────────────────────────
BACKEND_HOST = "49.200.100.22"
MODEL_PORTS  = [6004, 6005]
TIMEOUT_SEC  = 180
COMPONENT_DIR = Path(__file__).parent / "vad_component"
# ──────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Auto-VAD Hindi ASR",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────  Declare custom component  ────────────────────────
# Using declare_component so JS can call Streamlit.setComponentValue()
# and Python receives the audio payload — avoids all browser CORS/HTTPS issues.
_vad_component = components.declare_component(
    "vad_recorder",
    path=str(COMPONENT_DIR),
)

def vad_recorder(config: dict, key: str = "vad"):
    """Render the VAD component and return audio payload when speech ends."""
    return _vad_component(
        calibrationMs    = config["calibrationMs"],
        silenceTimeoutMs = config["silenceTimeoutMs"],
        energyMultiplier = config["energyMultiplier"],
        minSpeechMs      = config["minSpeechMs"],
        noiseAlpha       = config["noiseAlpha"],
        echoCancellation = config["echoCancellation"],
        noiseSuppression = config["noiseSuppression"],
        autoGainControl  = config["autoGainControl"],
        key=key,
        default=None,
    )

# ─────────────────────────────  Sidebar  ─────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Configuration")

    selected_port = st.selectbox(
        "Backend model port",
        MODEL_PORTS,
        format_func=lambda p: f"Port {p}",
    )
    backend_url = f"http://{BACKEND_HOST}:{selected_port}/streamlitTranscribe"
    st.caption(f"`{backend_url}`")

    st.markdown("---")
    st.markdown("### 🔊 VAD Parameters")
    calibration_ms = st.slider("Noise calibration time (ms)", 500, 4000, 1500, 100,
        help="Stay quiet during calibration so the app learns your room's noise.")
    silence_timeout_ms = st.slider("Silence-to-stop timeout (ms)", 600, 6000, 2000, 100,
        help="Silence duration before recording stops. Increase for slow speakers.")
    energy_multiplier = st.slider("Speech sensitivity (lower = more sensitive)", 1.0, 8.0, 2.8, 0.1,
        help="Speech threshold = noise_floor × this value.")
    min_speech_ms = st.slider("Minimum speech duration (ms)", 100, 3000, 400, 50,
        help="Clips shorter than this are discarded (avoids noise bursts).")
    noise_alpha = st.slider("Noise floor adaptation speed", 0.80, 0.999, 0.97, 0.001,
        format="%.3f",
        help="EMA coefficient. Higher = slower adaptation.")

    st.markdown("---")
    st.markdown("### 🎛️ Audio Capture")
    echo_cancel    = st.checkbox("Echo cancellation",       value=True)
    noise_suppress = st.checkbox("Browser noise suppress",  value=False)
    auto_gain      = st.checkbox("Auto gain control",       value=False)

    st.markdown("---")
    st.markdown("### 🔗 Why no 'Failed to fetch'?")
    st.success(
        "Audio travels **browser → Streamlit (HTTPS) → FastAPI (HTTP)**.\n\n"
        "The Python server makes the HTTP call — the browser never touches FastAPI directly, "
        "so CORS and mixed-content restrictions don't apply."
    )

    st.markdown("---")
    st.markdown("### ℹ️ How to use")
    st.info(
        "1. Click **Start Listening**\n"
        "2. Stay quiet during calibration (~1.5s)\n"
        "3. Start speaking — recording begins automatically\n"
        "4. Stop speaking — recording stops after silence timeout\n"
        "5. Transcription appears below automatically"
    )

# ────────────────────────────  Main Page  ────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

.result-card {
    background: #161921; border: 1px solid rgba(255,255,255,.07);
    border-radius: 12px; padding: 16px 18px; margin-bottom: 12px;
    font-family: 'IBM Plex Sans', sans-serif;
}
.card-header {
    display: flex; justify-content: space-between;
    font-size: 11px; color: #5a6478; margin-bottom: 12px;
    font-family: 'IBM Plex Mono', monospace;
}
.field-label {
    font-size: 10px; color: #5a6478; text-transform: uppercase;
    letter-spacing: .07em; margin-bottom: 4px;
}
.field-val {
    font-family: 'IBM Plex Mono', monospace; font-size: 12px;
    background: rgba(0,0,0,.3); border: 1px solid rgba(255,255,255,.06);
    border-radius: 6px; padding: 6px 10px; margin-bottom: 10px;
    word-break: break-word; color: #c9d1e0;
}
.field-en { color: #7dd87d !important; font-size: 13px !important; }
.chip {
    display: inline-block; font-size: 10px; padding: 2px 8px;
    border-radius: 99px; background: rgba(255,255,255,.06);
    color: #5a6478; font-family: 'IBM Plex Mono', monospace; margin-left: 6px;
}
.chip-rtt { color: #5b9cf6; }
.chip-dur { color: #3ddc84; }
</style>
""", unsafe_allow_html=True)

st.markdown("# 🎙️ Auto-VAD Hindi ASR")
st.caption("Hands-free · Browser VAD · Adaptive noise floor · Python-proxied to FastAPI")
st.markdown("---")

# ─────────────────────────  VAD Component  ───────────────────────────────────
vad_config = {
    "calibrationMs":    calibration_ms,
    "silenceTimeoutMs": silence_timeout_ms,
    "energyMultiplier": energy_multiplier,
    "minSpeechMs":      min_speech_ms,
    "noiseAlpha":       noise_alpha,
    "echoCancellation": echo_cancel,
    "noiseSuppression": noise_suppress,
    "autoGainControl":  auto_gain,
}

audio_payload = vad_recorder(vad_config, key="vad_main")

# ─────────────────────────  Handle incoming audio  ───────────────────────────
if "results" not in st.session_state:
    st.session_state.results = []

if "last_ts" not in st.session_state:
    st.session_state.last_ts = 0

if audio_payload and isinstance(audio_payload, dict):
    ts = audio_payload.get("ts", 0)

    # Deduplicate — Streamlit re-runs on every interaction, don't re-process same clip
    if ts != st.session_state.last_ts:
        st.session_state.last_ts = ts

        audio_b64  = audio_payload.get("audio_b64", "")
        mime_type  = audio_payload.get("mime_type", "audio/webm")
        filename   = audio_payload.get("filename", f"vad_{ts}.webm")

        if audio_b64:
            audio_bytes = base64.b64decode(audio_b64)

            # Determine extension from mime type
            if "ogg" in mime_type:   ext = "ogg"
            elif "mp4" in mime_type: ext = "mp4"
            else:                    ext = "webm"

            server_filename = filename if filename.endswith(f".{ext}") else f"{filename}.{ext}"

            # ── Python → FastAPI (server-side, no CORS) ───────────────────
            with st.spinner("Transcribing…"):
                t0 = time.perf_counter()
                try:
                    resp = requests.post(
                        backend_url,
                        data={
                            "client_filename": server_filename,
                            "panns_threshold": "0.2",
                            "vad_threshold":   "0.2",
                        },
                        files={
                            "file": (server_filename, io.BytesIO(audio_bytes), mime_type)
                        },
                        timeout=TIMEOUT_SEC,
                    )
                    rtt = round(time.perf_counter() - t0, 2)

                    if resp.status_code == 200:
                        data = resp.json()
                        st.session_state.results.insert(0, {
                            "status":    "ok",
                            "data":      data,
                            "rtt":       rtt,
                            "filename":  server_filename,
                            "timestamp": datetime.now().strftime("%H:%M:%S"),
                            "audio":     audio_bytes,
                            "mime":      mime_type,
                        })
                    else:
                        st.session_state.results.insert(0, {
                            "status":    "error",
                            "error":     f"HTTP {resp.status_code}: {resp.text[:300]}",
                            "rtt":       rtt,
                            "timestamp": datetime.now().strftime("%H:%M:%S"),
                        })
                except requests.exceptions.ConnectionError as e:
                    rtt = round(time.perf_counter() - t0, 2)
                    st.session_state.results.insert(0, {
                        "status":    "error",
                        "error":     f"Cannot connect to backend ({backend_url})\n\n{e}",
                        "rtt":       rtt,
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                    })
                except Exception as e:
                    rtt = round(time.perf_counter() - t0, 2)
                    st.session_state.results.insert(0, {
                        "status":    "error",
                        "error":     str(e),
                        "rtt":       rtt,
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                    })

            # Keep last 10 results
            st.session_state.results = st.session_state.results[:10]

# ─────────────────────────  Results  ─────────────────────────────────────────
st.markdown("---")
st.markdown("### 📋 Transcription Results")

if not st.session_state.results:
    st.info("Results will appear here automatically after each utterance.")
else:
    col_clear, _ = st.columns([1, 5])
    with col_clear:
        if st.button("🗑 Clear results"):
            st.session_state.results = []
            st.rerun()

    for i, r in enumerate(st.session_state.results):
        num = len(st.session_state.results) - i

        if r["status"] == "error":
            st.error(f"**Error #{num} · {r['timestamp']} · {r['rtt']}s**\n\n{r['error']}")
            continue

        data = r["data"]
        dur  = data.get("audio_duration_seconds")
        dur_str = f"{dur:.2f}s" if dur is not None else "—"

        st.markdown(f"""
<div class="result-card">
  <div class="card-header">
    <span>#{num} · {r['timestamp']}</span>
    <span>
      <span class="chip chip-dur">⏱ {dur_str}</span>
      <span class="chip chip-rtt">↩ {r['rtt']}s</span>
      <span class="chip">{r['filename']}</span>
    </span>
  </div>
  <div class="field-label">Hindi · raw</div>
  <div class="field-val">{data.get('raw_hindi', data.get('raw_transcription','—'))}</div>
  <div class="field-label">Hindi · corrected</div>
  <div class="field-val">{data.get('corrected_hindi','—')}</div>
  <div class="field-label">English translation</div>
  <div class="field-val field-en">{data.get('english_translation','—')}</div>
</div>
""", unsafe_allow_html=True)

        # Playback of the recorded clip
        with st.expander(f"▶ Play recorded audio #{num}"):
            st.audio(r["audio"], format=r["mime"])

# ─────────────────────────  Notes  ───────────────────────────────────────────
with st.expander("📖 Architecture & tuning notes"):
    st.markdown("""
    ### Why the original version failed
    | Problem | Cause | Fix |
    |---|---|---|
    | `Failed to fetch` | Browser on HTTPS (`streamlit.app`) tried to call HTTP FastAPI directly | Python now proxies the call — browser never touches FastAPI |
    | CORS errors | FastAPI had no `Access-Control-Allow-Origin` header | Moot — server-to-server has no CORS |

    ### New request flow
    ```
    Browser mic → Web Audio API (VAD) → MediaRecorder → base64 blob
        → Streamlit.setComponentValue()   [same-origin, no restrictions]
        → Streamlit Python                [receives base64, decodes to bytes]
        → requests.post(FastAPI)          [server-to-server, no CORS/HTTPS]
        → Results displayed in Streamlit
    ```

    ### VAD algorithm
    | Stage | Detail |
    |---|---|
    | Calibration | EMA of RMS during quiet period → establishes noise floor |
    | Speech start | `RMS > noise_floor × sensitivity` triggers `MediaRecorder.start()` |
    | Pause tolerance | Silence timer resets on each speech frame — pauses are safe |
    | Speech end | Continuous silence ≥ timeout → `MediaRecorder.stop()` |
    | Noise adaptation | Floor updates only during genuinely silent frames (< 55% of threshold) |
    | Short-clip guard | Clips shorter than min duration are silently discarded |

    ### Tuning for noisy environments
    | Problem | Fix |
    |---|---|
    | Cuts off mid-sentence | Increase **Silence timeout** |
    | Background noise triggers recording | Increase **Speech sensitivity** |
    | Quiet speaker not detected | Lower **Speech sensitivity** |
    | Room noise keeps adapting during speech | Increase **Noise floor adaptation speed** |

    ### To fix backend connection errors
    If you still see connection errors (not fetch errors), the backend itself may be down or
    the server IP/port may be wrong. Those appear as `ConnectionError` in Streamlit, not
    browser `Failed to fetch` — which means the routing fix is working correctly.
    """)

st.caption(f"Auto-VAD PoC · Python-proxied · backend `{backend_url}`")
