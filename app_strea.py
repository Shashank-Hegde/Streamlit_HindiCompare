#!/usr/bin/env python3
"""
Auto-VAD Hindi ASR — Fixed PoC v3
===================================

Why the previous version failed:
  - Missing `streamlit-component-lib` script in index.html
  - Without it, Streamlit.setComponentValue() doesn't exist in JS
  - Audio was recorded but never sent back to Python
  - Python never called FastAPI

Fix:
  - index.html now loads streamlit-component-lib from CDN
  - Streamlit.setComponentReady() + setComponentValue() work correctly
  - Python receives audio as base64, proxies to FastAPI via requests
  - No CORS / mixed-content issues (server-to-server call)

Folder layout required:
  your_project/
  ├── streamlit_vad_poc.py       ← this file
  └── vad_component/
      └── index.html             ← VAD iframe

Run:
  streamlit run streamlit_vad_poc.py
"""

import base64
import io
import time
from datetime import datetime
from pathlib import Path

import requests
import streamlit as st
import streamlit.components.v1 as components

# ── Config ────────────────────────────────────────────────────────────────────
BACKEND_HOST  = "49.200.100.22"
MODEL_PORTS   = [6004, 6005]
TIMEOUT_SEC   = 180
COMPONENT_DIR = Path(__file__).parent / "vad_component"

# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Auto-VAD Hindi ASR",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Declare the custom component ──────────────────────────────────────────────
# Using declare_component with path= serves index.html as an iframe.
# Python → JS: kwargs passed to declare_component() become event.detail.args in JS.
# JS → Python: Streamlit.setComponentValue(obj) returns obj as the function's return value.
_vad_comp = components.declare_component("vad_recorder", path=str(COMPONENT_DIR))

def vad_recorder(cfg: dict, key: str = "vad") -> dict | None:
    """Render VAD component. Returns audio payload dict when an utterance is captured."""
    return _vad_comp(
        calibrationMs    = cfg["calibrationMs"],
        silenceTimeoutMs = cfg["silenceTimeoutMs"],
        energyMultiplier = cfg["energyMultiplier"],
        minSpeechMs      = cfg["minSpeechMs"],
        noiseAlpha       = cfg["noiseAlpha"],
        echoCancellation = cfg["echoCancellation"],
        noiseSuppression = cfg["noiseSuppression"],
        autoGainControl  = cfg["autoGainControl"],
        key=key,
        default=None,
    )

# ── Sidebar ───────────────────────────────────────────────────────────────────
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

    calibration_ms = st.slider(
        "Noise calibration (ms)", 500, 4000, 1500, 100,
        help="Stay quiet during this phase. App learns room noise level.",
    )
    silence_timeout_ms = st.slider(
        "Silence-to-stop timeout (ms)", 600, 6000, 2000, 100,
        help="How long silence must last before recording stops. Increase for slower speakers.",
    )
    energy_multiplier = st.slider(
        "Speech sensitivity (lower = more sensitive)", 1.0, 8.0, 2.8, 0.1,
        help="Threshold = noise_floor × this. Lower in quiet rooms.",
    )
    min_speech_ms = st.slider(
        "Minimum speech duration (ms)", 100, 3000, 400, 50,
        help="Clips shorter than this are discarded (prevents noise bursts being sent).",
    )
    noise_alpha = st.slider(
        "Noise floor adaptation speed", 0.80, 0.999, 0.97, 0.001,
        format="%.3f",
        help="EMA coefficient. Higher = slower adaptation to room changes.",
    )

    st.markdown("---")
    st.markdown("### 🎛️ Audio Capture")
    echo_cancel    = st.checkbox("Echo cancellation",        value=True)
    noise_suppress = st.checkbox("Browser noise suppression", value=False)
    auto_gain      = st.checkbox("Auto gain control",         value=False)

    st.markdown("---")
    st.markdown("### 🔗 Architecture")
    st.success(
        "**No more 'Failed to fetch'**\n\n"
        "Browser → Streamlit Python (HTTPS) → FastAPI (HTTP)\n\n"
        "Python makes the HTTP call server-side — the browser never touches FastAPI directly."
    )
    st.markdown("### ℹ️ How to use")
    st.info(
        "1. Click **Start Listening**\n"
        "2. Stay quiet for ~1.5s calibration\n"
        "3. Speak in Hindi — recording starts automatically\n"
        "4. Stop speaking — recording stops after silence timeout\n"
        "5. Transcription appears below"
    )

# ── Main page ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
.res-card{
  background:#161921;border:1px solid rgba(255,255,255,.07);
  border-radius:12px;padding:16px 18px;margin-bottom:12px;
  font-family:'IBM Plex Sans',sans-serif;
}
.res-head{display:flex;justify-content:space-between;font-size:11px;color:#5a6478;margin-bottom:12px;font-family:'IBM Plex Mono',monospace}
.flbl{font-size:10px;color:#5a6478;text-transform:uppercase;letter-spacing:.07em;margin-bottom:3px}
.fval{font-family:'IBM Plex Mono',monospace;font-size:12px;background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.06);border-radius:6px;padding:6px 10px;margin-bottom:10px;word-break:break-word;color:#c9d1e0}
.fen{color:#7dd87d!important;font-size:13px!important}
.chip{display:inline-block;font-size:10px;padding:2px 8px;border-radius:99px;background:rgba(255,255,255,.06);color:#5a6478;font-family:'IBM Plex Mono',monospace;margin-left:6px}
.crtt{color:#5b9cf6}.cdur{color:#3ddc84}
</style>
""", unsafe_allow_html=True)

st.markdown("# 🎙️ Auto-VAD Hindi ASR")
st.caption("Hands-free · Browser VAD · Adaptive noise floor · Python-proxied to FastAPI")
st.markdown("---")

# ── Render VAD component ──────────────────────────────────────────────────────
vad_cfg = {
    "calibrationMs":    calibration_ms,
    "silenceTimeoutMs": silence_timeout_ms,
    "energyMultiplier": energy_multiplier,
    "minSpeechMs":      min_speech_ms,
    "noiseAlpha":       noise_alpha,
    "echoCancellation": echo_cancel,
    "noiseSuppression": noise_suppress,
    "autoGainControl":  auto_gain,
}

# This renders the iframe AND returns the audio payload when JS calls setComponentValue()
audio_payload = vad_recorder(vad_cfg, key="vad_main")

# ── Handle received audio ─────────────────────────────────────────────────────
if "results" not in st.session_state:
    st.session_state.results = []
if "last_ts" not in st.session_state:
    st.session_state.last_ts = 0

if audio_payload and isinstance(audio_payload, dict):
    ts = audio_payload.get("ts", 0)

    # Streamlit re-runs on every widget interaction — deduplicate by timestamp
    if ts and ts != st.session_state.last_ts:
        st.session_state.last_ts = ts

        audio_b64 = audio_payload.get("audio_b64", "")
        mime_type = audio_payload.get("mime_type", "audio/webm")
        filename  = audio_payload.get("filename",  f"vad_{ts}.webm")

        if audio_b64:
            audio_bytes = base64.b64decode(audio_b64)

            # ── Python → FastAPI (server-side, no CORS, no mixed-content) ──
            with st.spinner(f"Transcribing `{filename}`…"):
                t0 = time.perf_counter()
                try:
                    resp = requests.post(
                        backend_url,
                        data={
                            "client_filename": filename,
                            "panns_threshold": "0.2",
                            "vad_threshold":   "0.2",
                        },
                        files={"file": (filename, io.BytesIO(audio_bytes), mime_type)},
                        timeout=TIMEOUT_SEC,
                    )
                    rtt = round(time.perf_counter() - t0, 2)

                    if resp.status_code == 200:
                        st.session_state.results.insert(0, {
                            "status":    "ok",
                            "data":      resp.json(),
                            "rtt":       rtt,
                            "filename":  filename,
                            "timestamp": datetime.now().strftime("%H:%M:%S"),
                            "audio":     audio_bytes,
                            "mime":      mime_type,
                        })
                    else:
                        st.session_state.results.insert(0, {
                            "status":    "error",
                            "error":     f"HTTP {resp.status_code}: {resp.text[:400]}",
                            "rtt":       rtt,
                            "timestamp": datetime.now().strftime("%H:%M:%S"),
                        })

                except requests.exceptions.ConnectionError as e:
                    rtt = round(time.perf_counter() - t0, 2)
                    st.session_state.results.insert(0, {
                        "status":    "error",
                        "error":     (
                            f"Cannot reach backend at `{backend_url}`\n\n"
                            f"Check that the FastAPI server is running.\n\n`{e}`"
                        ),
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

            # Keep last 10
            st.session_state.results = st.session_state.results[:10]

# ── Display results ───────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 📋 Transcription Results")

if not st.session_state.results:
    st.info("Results will appear here automatically after each utterance.")
else:
    if st.button("🗑 Clear results"):
        st.session_state.results = []
        st.rerun()

    for i, r in enumerate(st.session_state.results):
        num = len(st.session_state.results) - i

        if r["status"] == "error":
            st.error(f"**Error #{num} · {r['timestamp']} · {r['rtt']}s**\n\n{r['error']}")
            continue

        d   = r["data"]
        dur = d.get("audio_duration_seconds")
        dur_s = f"{dur:.2f}s" if dur is not None else "—"

        raw_hi  = d.get("raw_hindi", d.get("raw_transcription", "—"))
        corr_hi = d.get("corrected_hindi", "—")
        eng     = d.get("english_translation", "—")

        st.markdown(f"""
<div class="res-card">
  <div class="res-head">
    <span>#{num} · {r['timestamp']}</span>
    <span>
      <span class="chip cdur">⏱ {dur_s}</span>
      <span class="chip crtt">↩ {r['rtt']}s</span>
      <span class="chip">{r['filename']}</span>
    </span>
  </div>
  <div class="flbl">Hindi · raw</div>
  <div class="fval">{raw_hi}</div>
  <div class="flbl">Hindi · corrected</div>
  <div class="fval">{corr_hi}</div>
  <div class="flbl">English translation</div>
  <div class="fval fen">{eng}</div>
</div>
""", unsafe_allow_html=True)

        with st.expander(f"▶ Play clip #{num}"):
            st.audio(r["audio"], format=r["mime"])

# ── Notes ─────────────────────────────────────────────────────────────────────
with st.expander("📖 What was fixed & how it works"):
    st.markdown("""
    ### Root cause of "Failed to fetch"
    The original auto-VAD app used `components.html()` which renders JS that called
    `fetch('http://...')` **directly from the browser**. Streamlit Cloud serves on HTTPS,
    so browsers block outgoing HTTP calls (mixed-content policy). CORS headers also blocked it.

    ### Root cause of "transcript not coming" (v2)
    `components.declare_component()` was used correctly, but `index.html` **did not load
    `streamlit-component-lib`**, so `Streamlit.setComponentValue()` didn't exist in JS.
    Audio was recorded but silently never sent to Python.

    ### Fix applied in v3
    ```html
    <!-- This one line was missing -->
    <script src="https://unpkg.com/streamlit-component-lib/dist/StreamlitLib.js"></script>
    ```
    Plus:
    - `Streamlit.setComponentReady()` — signals iframe is ready
    - `Streamlit.setComponentValue({audio_b64, ...})` — sends audio to Python
    - `document.addEventListener("streamlit:render", ...)` — receives args from Python

    ### Request flow (fixed)
    ```
    Mic → Web Audio API → MediaRecorder → base64
      → Streamlit.setComponentValue()    [same-origin iframe → Streamlit]
      → Python receives base64           [decode to bytes]
      → requests.post(FastAPI)           [server-to-server, no CORS]
      → JSON result displayed
    ```

    ### VAD algorithm
    | Stage | Detail |
    |---|---|
    | Calibration | EMA of RMS during quiet → establishes `noise_floor` |
    | Speech start | `RMS > noise_floor × sensitivity` → `MediaRecorder.start()` |
    | Pause tolerance | Silence timer resets on every speech frame |
    | Speech end | `silence_timeout_ms` continuous silence → `MediaRecorder.stop()` |
    | Noise adapt | Floor updates only when `RMS < threshold × 0.55` (truly quiet) |
    | Short-clip guard | Clips < `min_speech_ms` silently discarded |
    """)

st.caption(f"Auto-VAD PoC v3 · Python-proxied · `{backend_url}`")
