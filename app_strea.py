#!/usr/bin/env python3
"""
Auto-VAD Hindi ASR — Proof of Concept
--------------------------------------
Replaces manual mic button clicks with browser-side Voice Activity Detection.

Algorithm:
  1. Calibration phase  : measure background noise for N seconds (stay quiet)
  2. Adaptive noise floor: exponential moving average updated only during silence
  3. Speech start       : RMS energy > noise_floor × sensitivity_multiplier
  4. Pause tolerance    : silence timer resets on each speech frame (no mid-sentence cuts)
  5. Speech end         : silence_timer expires after configurable timeout
  6. Short-clip guard   : recordings shorter than min_speech_ms are discarded

Noisy-environment robustness:
  - Noise floor adapts continuously, only during clear-silence frames
  - Browser echoCancellation is applied upstream
  - All thresholds are relative (ratio-based), not absolute
  - User can tune sensitivity and silence timeout from the sidebar
"""

import json
import streamlit as st
import streamlit.components.v1 as components

# ──────────────────────────────────────────────────────────────────────────────
BACKEND_HOST = "49.200.100.22"
MODEL_PORTS  = [6004, 6005]
# ──────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Auto-VAD Hindi ASR",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────  Sidebar  ─────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Configuration")

    selected_port = st.selectbox(
        "Backend model port",
        MODEL_PORTS,
        format_func=lambda p: f"Port {p}",
    )
    st.caption(f"Endpoint: `http://{BACKEND_HOST}:{selected_port}/streamlitTranscribe`")

    st.markdown("---")
    st.markdown("### 🔊 VAD Parameters")

    calibration_ms = st.slider(
        "Noise calibration time (ms)",
        500, 4000, 1500, 100,
        help="Stay quiet during this phase so the app learns your room's background noise.",
    )
    silence_timeout_ms = st.slider(
        "Silence-to-stop timeout (ms)",
        600, 6000, 2000, 100,
        help=(
            "How long continuous silence must last before recording stops. "
            "Increase for slow/paced speakers or if recordings cut off too early."
        ),
    )
    energy_multiplier = st.slider(
        "Speech sensitivity  (lower = more sensitive)",
        1.0, 8.0, 2.8, 0.1,
        help=(
            "Speech is detected when RMS energy > noise_floor × this value. "
            "Lower it in a quiet room; raise it if background noise triggers false starts."
        ),
    )
    min_speech_ms = st.slider(
        "Minimum speech duration (ms)",
        100, 3000, 400, 50,
        help="Recordings shorter than this are silently discarded (avoids noise bursts).",
    )
    noise_alpha = st.slider(
        "Noise floor adaptation speed",
        0.80, 0.999, 0.97, 0.001,
        format="%.3f",
        help=(
            "EMA coefficient for noise-floor updates. "
            "Higher → slower adaptation (stable floor). "
            "Lower → tracks room noise changes faster."
        ),
    )

    st.markdown("---")
    st.markdown("### 🎛️ Audio Capture")
    echo_cancel   = st.checkbox("Echo cancellation",    value=True)
    noise_suppress = st.checkbox("Browser noise suppress", value=False,
                                  help="Let the browser remove background noise before VAD. "
                                       "Can help in very noisy rooms, but may alter speech.")
    auto_gain     = st.checkbox("Auto gain control",    value=False)

    st.markdown("---")
    st.markdown("### ℹ️ How it works")
    st.info(
        "1. Click **Start Listening**\n"
        "2. Stay quiet during calibration\n"
        "3. Start speaking — recording begins automatically\n"
        "4. Pause or finish — recording stops after the silence timeout\n"
        "5. Results appear below the waveform"
    )

# ────────────────────────────  Main Page  ────────────────────────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown("# 🎙️ Auto-VAD Hindi ASR")
st.caption(
    "Hands-free speech capture · Browser VAD · Adaptive noise floor · No button clicks needed"
)
st.markdown("---")

# Build config dict to inject into JS
vad_config = {
    "backendUrl":        f"http://{BACKEND_HOST}:{selected_port}/streamlitTranscribe",
    "calibrationMs":     calibration_ms,
    "silenceTimeoutMs":  silence_timeout_ms,
    "energyMultiplier":  energy_multiplier,
    "minSpeechMs":       min_speech_ms,
    "noiseAlpha":        noise_alpha,
    "echoCancellation":  echo_cancel,
    "noiseSuppression":  noise_suppress,
    "autoGainControl":   auto_gain,
}

# ─────────────────────────  HTML / JS Component  ─────────────────────────────
# NOTE: we inject CONFIG via string replace to avoid escaping every `{}` in JS.

HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:        #0d0f14;
    --surface:   #161921;
    --border:    rgba(255,255,255,.07);
    --text:      #c9d1e0;
    --muted:     #5a6478;
    --green:     #3ddc84;
    --red:       #ff4d6a;
    --amber:     #ffb347;
    --blue:      #5b9cf6;
    --font-mono: 'IBM Plex Mono', monospace;
    --font-sans: 'IBM Plex Sans', sans-serif;
  }

  html, body {
    background: transparent;
    color: var(--text);
    font-family: var(--font-sans);
    font-size: 13px;
    line-height: 1.5;
    padding: 0 4px;
  }

  /* ── Status Bar ───────────────────────────────── */
  .status-bar {
    display: flex;
    align-items: center;
    gap: 10px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 14px;
    margin-bottom: 10px;
  }
  .dot {
    width: 11px; height: 11px;
    border-radius: 50%;
    flex-shrink: 0;
    background: var(--muted);
    transition: background .25s;
  }
  .dot.idle        { background: var(--muted); }
  .dot.calibrating { background: var(--amber); animation: blink 1s infinite; }
  .dot.listening   { background: var(--green); }
  .dot.recording   { background: var(--red);   animation: blink .45s infinite; }
  .dot.processing  { background: var(--blue);  animation: blink .6s  infinite; }
  .dot.error       { background: var(--red); }

  @keyframes blink {
    0%,100% { opacity:1; }
    50%      { opacity:.35; }
  }

  .status-text { flex: 1; font-size: 13px; font-weight: 500; }
  .rec-badge {
    display: none;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    color: var(--red);
    font-family: var(--font-mono);
    font-weight: 500;
    letter-spacing: .04em;
  }
  .rec-badge.show { display: flex; }

  /* ── Waveform ─────────────────────────────────── */
  #waveform {
    display: block;
    width: 100%;
    height: 88px;
    border-radius: 8px;
    background: var(--surface);
    border: 1px solid var(--border);
    margin-bottom: 8px;
  }

  /* ── Level Meters ─────────────────────────────── */
  .meters {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
    margin-bottom: 10px;
  }
  .meter { }
  .meter-label {
    font-size: 10px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: .06em;
    margin-bottom: 4px;
    display: flex;
    justify-content: space-between;
  }
  .meter-label span { font-family: var(--font-mono); color: var(--text); }
  .meter-track {
    height: 5px;
    background: rgba(255,255,255,.06);
    border-radius: 99px;
    overflow: hidden;
  }
  .meter-fill {
    height: 100%;
    border-radius: 99px;
    transition: width .05s linear;
    width: 0%;
  }
  #mEnergy .meter-fill  { background: var(--blue); }
  #mNoise  .meter-fill  { background: var(--amber); }
  #mThresh .meter-fill  { background: var(--red); }

  /* ── Controls ─────────────────────────────────── */
  .controls {
    display: flex;
    gap: 8px;
    margin-bottom: 14px;
  }
  button {
    padding: 8px 20px;
    border: none;
    border-radius: 8px;
    font-family: var(--font-sans);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: all .15s;
    letter-spacing: .02em;
  }
  #btnStart {
    background: var(--green);
    color: #0a1a10;
  }
  #btnStart:hover:not(:disabled) { filter: brightness(1.1); }
  #btnStart:disabled { background: #1e2430; color: var(--muted); cursor: not-allowed; }

  #btnStop {
    background: rgba(255,77,106,.15);
    color: var(--red);
    border: 1px solid rgba(255,77,106,.35);
  }
  #btnStop:hover:not(:disabled) { background: rgba(255,77,106,.25); }
  #btnStop:disabled { opacity: .4; cursor: not-allowed; }

  #btnClear {
    margin-left: auto;
    background: transparent;
    color: var(--muted);
    border: 1px solid var(--border);
    font-size: 12px;
    padding: 8px 14px;
  }
  #btnClear:hover { color: var(--text); border-color: rgba(255,255,255,.2); }

  /* ── Pause Progress ───────────────────────────── */
  .pause-track {
    height: 3px;
    background: rgba(255,255,255,.06);
    border-radius: 99px;
    overflow: hidden;
    margin-bottom: 10px;
    opacity: 0;
    transition: opacity .2s;
  }
  .pause-track.show { opacity: 1; }
  .pause-fill {
    height: 100%;
    background: var(--amber);
    border-radius: 99px;
    transition: width .1s linear;
    width: 0%;
  }

  /* ── Divider ──────────────────────────────────── */
  .section-label {
    font-size: 10px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: .1em;
    padding: 2px 0 8px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 10px;
  }

  /* ── Result Cards ─────────────────────────────── */
  .result-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 14px;
    margin-bottom: 8px;
    animation: slideIn .25s ease;
  }
  @keyframes slideIn {
    from { opacity: 0; transform: translateY(-6px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
  }
  .card-num {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--muted);
  }
  .card-meta {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
  }
  .chip {
    font-size: 10px;
    padding: 2px 7px;
    border-radius: 99px;
    background: rgba(255,255,255,.06);
    color: var(--muted);
    font-family: var(--font-mono);
  }
  .chip.rtt  { color: var(--blue); }
  .chip.dur  { color: var(--green); }

  .field-row { margin-bottom: 7px; }
  .field-label {
    font-size: 10px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: .07em;
    margin-bottom: 3px;
  }
  .field-val {
    font-family: var(--font-mono);
    font-size: 12px;
    background: rgba(0,0,0,.25);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 5px 9px;
    min-height: 26px;
    word-break: break-word;
    color: var(--text);
  }
  .field-val.en { color: #7dd87d; font-size: 13px; }

  .error-card {
    background: rgba(255,77,106,.07);
    border: 1px solid rgba(255,77,106,.25);
    border-radius: 10px;
    padding: 10px 14px;
    color: #ff8fa0;
    font-size: 12px;
    margin-bottom: 8px;
    animation: slideIn .25s ease;
  }
  .error-card strong { display: block; margin-bottom: 4px; color: var(--red); }

  #emptyState {
    text-align: center;
    color: var(--muted);
    padding: 24px 0;
    font-size: 12px;
  }
</style>
</head>
<body>
<div style="max-width:860px">

  <!-- Status Bar -->
  <div class="status-bar">
    <div class="dot idle" id="dot"></div>
    <span class="status-text" id="statusText">Click "Start Listening" to begin</span>
    <div class="rec-badge" id="recBadge">● REC</div>
  </div>

  <!-- Waveform Canvas -->
  <canvas id="waveform" width="860" height="88"></canvas>

  <!-- Level Meters -->
  <div class="meters">
    <div class="meter" id="mEnergy">
      <div class="meter-label">Energy <span id="valEnergy">0.0000</span></div>
      <div class="meter-track"><div class="meter-fill" id="fillEnergy"></div></div>
    </div>
    <div class="meter" id="mNoise">
      <div class="meter-label">Noise floor <span id="valNoise">0.0000</span></div>
      <div class="meter-track"><div class="meter-fill" id="fillNoise"></div></div>
    </div>
    <div class="meter" id="mThresh">
      <div class="meter-label">Threshold <span id="valThresh">0.0000</span></div>
      <div class="meter-track"><div class="meter-fill" id="fillThresh"></div></div>
    </div>
  </div>

  <!-- Pause progress bar -->
  <div class="pause-track" id="pauseTrack">
    <div class="pause-fill" id="pauseFill"></div>
  </div>

  <!-- Controls -->
  <div class="controls">
    <button id="btnStart" onclick="startListening()">🎙️ Start Listening</button>
    <button id="btnStop"  onclick="stopListening()" disabled>⏹ Stop</button>
    <button id="btnClear" onclick="clearResults()">Clear results</button>
  </div>

  <!-- Results -->
  <div class="section-label">Transcription Results</div>
  <div id="resultsContainer">
    <div id="emptyState">Results will appear here after each utterance…</div>
  </div>

</div>

<script>
/*__INJECT_CONFIG__*/

// ── State ────────────────────────────────────────────────────────────────────
let audioCtx     = null;
let analyser     = null;
let stream       = null;
let mediaRec     = null;
let chunks       = [];
let afId         = null;       // requestAnimationFrame id
let isListening  = false;
let isRecording  = false;
let noiseFloor   = 0.005;
let speechStart  = null;
let lastSpeech   = null;
let resultCount  = 0;
const MAX_METER  = 0.6;       // RMS value that maps to 100% meter width

// ── DOM refs ─────────────────────────────────────────────────────────────────
const canvas   = document.getElementById('waveform');
const gfx      = canvas.getContext('2d');
const dot      = document.getElementById('dot');
const stText   = document.getElementById('statusText');
const recBadge = document.getElementById('recBadge');
const pauseTrack = document.getElementById('pauseTrack');
const pauseFill  = document.getElementById('pauseFill');

// ── Status helper ─────────────────────────────────────────────────────────────
function setStatus(state, msg) {
  dot.className = 'dot ' + state;
  stText.textContent = msg;
  recBadge.classList.toggle('show', state === 'recording');
}

// ── Waveform drawing ──────────────────────────────────────────────────────────
function drawWaveform(data, rms) {
  const W = canvas.width, H = canvas.height;
  gfx.clearRect(0,0,W,H);
  gfx.fillStyle = '#161921';
  gfx.fillRect(0,0,W,H);

  // Threshold dashed line
  const thresh = noiseFloor * CONFIG.energyMultiplier;
  const threshY = H/2 - Math.min(thresh, MAX_METER)/MAX_METER * (H/2 * 0.85);
  gfx.beginPath();
  gfx.strokeStyle = 'rgba(255,77,106,0.35)';
  gfx.lineWidth = 1;
  gfx.setLineDash([5,4]);
  gfx.moveTo(0, threshY); gfx.lineTo(W, threshY);
  gfx.stroke();
  gfx.setLineDash([]);

  // Waveform
  const color = isRecording ? '#ff4d6a' : '#5b9cf6';
  gfx.beginPath();
  gfx.strokeStyle = color;
  gfx.lineWidth = 1.5;
  const step = W / data.length;
  for (let i = 0; i < data.length; i++) {
    const x = i * step;
    const y = H/2 + data[i] * (H/2 * 0.85);
    i === 0 ? gfx.moveTo(x,y) : gfx.lineTo(x,y);
  }
  gfx.stroke();

  // Glow fill under waveform when recording
  if (isRecording) {
    gfx.beginPath();
    gfx.strokeStyle = 'transparent';
    for (let i = 0; i < data.length; i++) {
      const x = i * step;
      const y = H/2 + data[i] * (H/2 * 0.85);
      i === 0 ? gfx.moveTo(x,y) : gfx.lineTo(x,y);
    }
    gfx.lineTo(W, H/2); gfx.lineTo(0, H/2);
    gfx.closePath();
    gfx.fillStyle = 'rgba(255,77,106,0.07)';
    gfx.fill();
  }

  // Centre line
  gfx.beginPath();
  gfx.strokeStyle = 'rgba(255,255,255,0.07)';
  gfx.lineWidth = 0.5;
  gfx.moveTo(0,H/2); gfx.lineTo(W,H/2);
  gfx.stroke();
}

// ── Meter update ──────────────────────────────────────────────────────────────
function updateMeters(rms) {
  const thresh = noiseFloor * CONFIG.energyMultiplier;
  const toW = v => Math.min(v / MAX_METER * 100, 100).toFixed(1) + '%';
  document.getElementById('fillEnergy').style.width = toW(rms);
  document.getElementById('fillNoise' ).style.width = toW(noiseFloor);
  document.getElementById('fillThresh').style.width = toW(thresh);
  document.getElementById('valEnergy' ).textContent = rms.toFixed(4);
  document.getElementById('valNoise'  ).textContent = noiseFloor.toFixed(4);
  document.getElementById('valThresh' ).textContent = thresh.toFixed(4);
}

// ── Calibration loop ──────────────────────────────────────────────────────────
function runCalibration(endTime) {
  if (!isListening) return;
  const data = new Float32Array(analyser.fftSize);
  analyser.getFloatTimeDomainData(data);
  const rms = Math.sqrt(data.reduce((s,v) => s + v*v, 0) / data.length);

  noiseFloor = CONFIG.noiseAlpha * noiseFloor + (1 - CONFIG.noiseAlpha) * Math.max(rms, 0.0002);

  drawWaveform(data, rms);
  updateMeters(rms);

  const remaining = Math.max(0, endTime - Date.now());
  setStatus('calibrating', `Calibrating noise floor… ${(remaining/1000).toFixed(1)}s remaining — please stay quiet`);

  if (Date.now() < endTime) {
    afId = requestAnimationFrame(() => runCalibration(endTime));
  } else {
    setStatus('listening', `Listening — noise floor: ${noiseFloor.toFixed(4)} · threshold: ${(noiseFloor * CONFIG.energyMultiplier).toFixed(4)}`);
    afId = requestAnimationFrame(runVAD);
  }
}

// ── Main VAD loop ─────────────────────────────────────────────────────────────
function runVAD() {
  if (!isListening) return;

  const data = new Float32Array(analyser.fftSize);
  analyser.getFloatTimeDomainData(data);
  const rms = Math.sqrt(data.reduce((s,v) => s + v*v, 0) / data.length);

  drawWaveform(data, rms);
  updateMeters(rms);

  const thresh = noiseFloor * CONFIG.energyMultiplier;
  const now    = Date.now();

  if (rms > thresh) {
    // ── Speech frame ───────────────────────────────────────────────────────
    // Do NOT update noise floor during active speech
    if (!isRecording) {
      beginRecording();
    }
    lastSpeech = now;
    pauseTrack.classList.remove('show');
    pauseFill.style.width = '0%';
    setStatus('recording', `Recording…  energy: ${rms.toFixed(4)}`);

  } else {
    // ── Silence frame ──────────────────────────────────────────────────────
    // Only update noise floor during genuinely quiet frames
    if (rms < thresh * 0.55) {
      noiseFloor = CONFIG.noiseAlpha * noiseFloor + (1 - CONFIG.noiseAlpha) * Math.max(rms, 0.0002);
    }

    if (isRecording && lastSpeech !== null) {
      const silenceMs = now - lastSpeech;
      const silencePct = Math.min(silenceMs / CONFIG.silenceTimeoutMs * 100, 100);

      // Show pause progress bar
      pauseTrack.classList.add('show');
      pauseFill.style.width = silencePct.toFixed(1) + '%';

      if (silenceMs >= CONFIG.silenceTimeoutMs) {
        const duration = now - speechStart;
        pauseTrack.classList.remove('show');
        pauseFill.style.width = '0%';
        if (duration >= CONFIG.minSpeechMs) {
          finishRecording();
        } else {
          discardRecording(`clip too short (${duration}ms < ${CONFIG.minSpeechMs}ms minimum)`);
        }
      } else {
        const left = ((CONFIG.silenceTimeoutMs - silenceMs) / 1000).toFixed(1);
        setStatus('recording', `Pause detected · stopping in ${left}s`);
      }
    } else {
      setStatus('listening', `Listening — floor: ${noiseFloor.toFixed(4)} · thresh: ${(noiseFloor * CONFIG.energyMultiplier).toFixed(4)}`);
    }
  }

  afId = requestAnimationFrame(runVAD);
}

// ── Recording control ─────────────────────────────────────────────────────────
function getMimeType() {
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/ogg',
    'audio/mp4',
  ];
  for (const m of candidates) {
    if (MediaRecorder.isTypeSupported(m)) return m;
  }
  return '';
}

function beginRecording() {
  chunks = [];
  const mime = getMimeType();
  try {
    mediaRec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
  } catch(e) {
    mediaRec = new MediaRecorder(stream);
  }
  mediaRec.ondataavailable = e => { if (e.data && e.data.size > 0) chunks.push(e.data); };
  mediaRec.onstop = submitAudio;
  mediaRec.start(80);   // collect chunks every 80 ms
  isRecording = true;
  speechStart = Date.now();
  lastSpeech  = Date.now();
}

function finishRecording() {
  if (!isRecording) return;
  isRecording = false;
  lastSpeech  = null;
  setStatus('processing', 'Processing…');
  mediaRec.stop();
}

function discardRecording(reason) {
  if (!isRecording) return;
  isRecording = false;
  lastSpeech  = null;
  const saved = mediaRec.onstop;   // clear so submitAudio is NOT called
  mediaRec.onstop = () => {};
  mediaRec.stop();
  chunks = [];
  setStatus('listening', `Discarded (${reason})`);
  setTimeout(() => {
    if (isListening) setStatus('listening', `Listening — floor: ${noiseFloor.toFixed(4)}`);
  }, 1800);
}

// ── Submit audio to FastAPI ───────────────────────────────────────────────────
async function submitAudio() {
  if (!chunks.length) {
    setStatus('listening', 'Nothing captured — listening again');
    return;
  }

  const blob     = new Blob(chunks, { type: chunks[0].type || 'audio/webm' });
  const ext      = blob.type.includes('ogg') ? 'ogg' : blob.type.includes('mp4') ? 'mp4' : 'webm';
  const filename = `vad_${Date.now()}.${ext}`;

  const fd = new FormData();
  fd.append('file',            blob, filename);
  fd.append('client_filename', filename);
  fd.append('panns_threshold', '0.2');
  fd.append('vad_threshold',   '0.2');

  const t0 = performance.now();
  try {
    const resp = await fetch(CONFIG.backendUrl, { method: 'POST', body: fd });
    const rtt  = ((performance.now() - t0) / 1000).toFixed(2);
    if (!resp.ok) {
      showError(`HTTP ${resp.status}: ${await resp.text()}`, rtt);
    } else {
      showResult(await resp.json(), rtt, filename);
    }
  } catch (err) {
    const rtt = ((performance.now() - t0) / 1000).toFixed(2);
    showError(err.message, rtt);
  }

  chunks = [];
  if (isListening) setStatus('listening', `Listening — floor: ${noiseFloor.toFixed(4)}`);
}

// ── Result display ────────────────────────────────────────────────────────────
function showResult(data, rtt, filename) {
  resultCount++;
  document.getElementById('emptyState')?.remove();

  const dur = data.audio_duration_seconds != null
    ? data.audio_duration_seconds.toFixed(2) + 's'
    : '—';

  const card = document.createElement('div');
  card.className = 'result-card';
  card.innerHTML = `
    <div class="card-header">
      <span class="card-num">#${resultCount} · ${new Date().toLocaleTimeString()}</span>
      <div class="card-meta">
        <span class="chip dur">⏱ ${dur}</span>
        <span class="chip rtt">↩ ${rtt}s</span>
        <span class="chip">${filename}</span>
      </div>
    </div>
    <div class="field-row">
      <div class="field-label">Hindi · raw</div>
      <div class="field-val">${escHtml(data.raw_hindi || data.raw_transcription || '—')}</div>
    </div>
    <div class="field-row">
      <div class="field-label">Hindi · corrected</div>
      <div class="field-val">${escHtml(data.corrected_hindi || '—')}</div>
    </div>
    <div class="field-row">
      <div class="field-label">English translation</div>
      <div class="field-val en">${escHtml(data.english_translation || '—')}</div>
    </div>
  `;
  document.getElementById('resultsContainer').prepend(card);
  trimResults(10);
}

function showError(msg, rtt) {
  resultCount++;
  document.getElementById('emptyState')?.remove();
  const card = document.createElement('div');
  card.className = 'error-card';
  card.innerHTML = `<strong>Error #${resultCount} · RTT ${rtt}s</strong>${escHtml(msg)}`;
  document.getElementById('resultsContainer').prepend(card);
  trimResults(10);
}

function trimResults(max) {
  const c = document.getElementById('resultsContainer');
  while (c.children.length > max) c.removeChild(c.lastChild);
}

function clearResults() {
  const c = document.getElementById('resultsContainer');
  c.innerHTML = '<div id="emptyState">Results will appear here after each utterance…</div>';
  resultCount = 0;
}

function escHtml(s) {
  return String(s)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}

// ── Start / Stop ──────────────────────────────────────────────────────────────
async function startListening() {
  document.getElementById('btnStart').disabled = true;
  setStatus('calibrating', 'Requesting microphone…');

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount:    1,
        sampleRate:      16000,
        echoCancellation: CONFIG.echoCancellation,
        noiseSuppression: CONFIG.noiseSuppression,
        autoGainControl:  CONFIG.autoGainControl,
      }
    });
  } catch (err) {
    setStatus('error', 'Microphone access denied: ' + err.message);
    document.getElementById('btnStart').disabled = false;
    return;
  }

  audioCtx = new AudioContext({ sampleRate: 16000 });
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 2048;
  analyser.smoothingTimeConstant = 0.25;
  audioCtx.createMediaStreamSource(stream).connect(analyser);

  isListening = true;
  noiseFloor  = 0.005;
  document.getElementById('btnStop').disabled = false;

  const calEnd = Date.now() + CONFIG.calibrationMs;
  afId = requestAnimationFrame(() => runCalibration(calEnd));
}

function stopListening() {
  isListening = false;
  if (afId)  cancelAnimationFrame(afId);
  if (isRecording && mediaRec) {
    isRecording = false;
    mediaRec.onstop = () => {};
    mediaRec.stop();
  }
  if (stream)   { stream.getTracks().forEach(t => t.stop()); stream = null; }
  if (audioCtx) { audioCtx.close(); audioCtx = null; }

  pauseTrack.classList.remove('show');
  document.getElementById('btnStart').disabled = false;
  document.getElementById('btnStop').disabled  = true;
  setStatus('idle', 'Stopped — click "Start Listening" to begin again');

  // Clear waveform
  const W = canvas.width, H = canvas.height;
  gfx.fillStyle = '#161921';
  gfx.fillRect(0,0,W,H);
}

window.addEventListener('beforeunload', stopListening);
</script>
</body>
</html>
"""

config_js    = f"const CONFIG = {json.dumps(vad_config, indent=2)};"
vad_html     = HTML_TEMPLATE.replace("/*__INJECT_CONFIG__*/", config_js)

components.html(vad_html, height=730, scrolling=False)

# ─────────────────────────  Footer notes  ────────────────────────────────────
with st.expander("📖 Implementation notes", expanded=False):
    st.markdown("""
    ### Browser-side VAD algorithm

    | Stage | What happens |
    |---|---|
    | **Calibration** | Measures background noise for N seconds using an EMA of RMS energy. |
    | **Detection** | Each animation frame (~60 fps) computes the RMS of a 2048-sample window. |
    | **Speech start** | RMS > `noise_floor × sensitivity_multiplier` triggers `MediaRecorder.start()`. |
    | **Pause tolerance** | Silence timer resets on each speech frame — pauses up to the timeout are ignored. |
    | **Speech end** | `silence_timeout_ms` of uninterrupted silence calls `MediaRecorder.stop()`. |
    | **Noise adaptation** | Floor is updated only during clear-silence frames (RMS < 55% of threshold). |
    | **Short-clip guard** | Recordings shorter than `min_speech_ms` are silently discarded. |

    ### Why this works in noisy environments
    - Thresholds are **relative** (ratio-based), not fixed values.
    - The noise floor adapts continuously, so a sudden increase in ambient noise
      raises the threshold rather than causing false triggers.
    - Browser `echoCancellation` removes feedback and reverb before the signal
      reaches the VAD.

    ### Audio path
    ```
    Microphone → AudioContext (16 kHz) → AnalyserNode → VAD loop
                                       ↘ MediaRecorder → WAV/WebM blob → FastAPI /streamlitTranscribe
    ```

    ### Tuning tips
    | Problem | Fix |
    |---|---|
    | Recording stops mid-sentence | Increase **Silence timeout** |
    | Background noise triggers recording | Increase **Speech sensitivity** |
    | Quiet speakers not detected | Lower **Speech sensitivity** |
    | Clips in noisy rooms start too late | Lower **Noise calibration time** & speak louder |
    | Short coughs/noise bursts recorded | Increase **Minimum speech duration** |
    """)

st.caption(
    "Auto-VAD PoC · browser-side energy VAD + adaptive noise floor · "
    f"backend `{BACKEND_HOST}:{selected_port}`"
)
