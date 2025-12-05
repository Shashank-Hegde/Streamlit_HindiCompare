import io
import time  # <-- NEW
from datetime import datetime

import requests
import streamlit as st

BACKEND_HOST = "49.200.100.22"
MODEL_PORTS = [6004, 6005]  # FastAPI apps with /streamlitTranscribe
TIMEOUT_SEC = 180

st.set_page_config(page_title="Hindi ASR – Compare Two Models", layout="wide")

st.title("Hindi ASR – Compare Two Models")

st.caption(
    f"Speak in Hindi or mixture of Hindi and English"
)

st.markdown("---")

# -------------------- Audio input (record or upload) --------------------

st.subheader("1. Provide Hindi audio")

input_method = st.radio(
    "Choose input method:",
    ["Record with microphone", "Upload WAV file"],
    index=0,
    key="audio_input_method",
)

audio_bytes = None

if input_method == "Record with microphone":
    audio_file = st.audio_input(
        "Click to record your Hindi audio, then click again to stop:",
        key="audio_rec",
    )
    if audio_file is not None:
        audio_bytes = audio_file.getvalue()

elif input_method == "Upload WAV file":
    uploaded_file = st.file_uploader(
        "Upload a .wav file with Hindi audio:",
        type=["wav"],
        key="audio_upload",
    )
    if uploaded_file is not None:
        # Read the raw bytes from the uploaded WAV
        audio_bytes = uploaded_file.read()

if audio_bytes is None:
    if input_method == "Record with microphone":
        st.info("👆 Record some audio to begin.")
    else:
        st.info("👆 Upload a .wav file to begin.")
    st.stop()

st.success("Audio ready.")
st.audio(audio_bytes, format="audio/wav")

st.markdown("---")
st.subheader("2. Send to models and view outputs")

if "results" not in st.session_state:
    st.session_state["results"] = None

if "audio_label" not in st.session_state:
    st.session_state["audio_label"] = None

col_btn, _ = st.columns([1, 3])

with col_btn:
    if st.button("Send to both models", type="primary"):
        # ---- Generate ONE shared filename for this audio ----
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        audio_label = f"streamlit_hindi_{ts}.wav"
        st.session_state["audio_label"] = audio_label

        results = {}
        for idx, port in enumerate(MODEL_PORTS, start=1):
            model_label = f"Model {idx}, (Port {port})"
            url = f"http://{BACKEND_HOST}:{port}/streamlitTranscribe"

            try:
                start_t = time.perf_counter()
                resp = requests.post(
                    url,
                    data={"client_filename": audio_label},  # shared logical name
                    files={
                        "file": (
                            "recording.wav",           # form filename
                            io.BytesIO(audio_bytes),  # same bytes to both models
                            "audio/wav",
                        )
                    },
                    timeout=TIMEOUT_SEC,
                )
                rtt = time.perf_counter() - start_t  # seconds

                if resp.status_code != 200:
                    results[model_label] = {
                        "error": f"HTTP {resp.status_code}: {resp.text}",
                        "rtt_seconds": round(rtt, 3),
                    }
                else:
                    data = resp.json()
                    # attach RTT to the model's JSON so it shows up in UI
                    data["rtt_seconds"] = round(rtt, 3)
                    results[model_label] = data
            except Exception as e:
                results[model_label] = {
                    "error": str(e),
                    "rtt_seconds": None,
                }

        st.session_state["results"] = results

# -------------------- Show results --------------------

st.markdown("---")
st.subheader("3. Model Outputs")

if st.session_state.get("audio_label"):
    st.markdown(
        f"**Shared audio filename for this run (client label):** "
        f"`{st.session_state['audio_label']}`"
    )

results = st.session_state.get("results")
if not results:
    st.info("Run inference first by clicking **Send to both models**.")
    st.stop()

col1, col2 = st.columns(2)
cols = [col1, col2]

for (model_label, result), col in zip(results.items(), cols):
    with col:
        st.markdown(f"### {model_label}")

        # RTT line (even if there was an error)
        rtt_val = result.get("rtt_seconds")
        if rtt_val is not None:
            st.markdown(f"**RTT (request–response, s):** `{rtt_val}`")

        if "error" in result:
            st.error(f"Request failed:\n\n`{result['error']}`")
            continue

        # Expecting the JSON from /streamlitTranscribe
        st.markdown(
            f"**Saved file on server:** `{result.get('file','?')}`  \n"
            f"**Duration (s):** `{result.get('audio_duration_seconds','?')}`  \n"
            f"**Speech probability:** `{result.get('speech_probability','?')}`"
        )

        st.markdown("**Hindi (raw):**")
        st.code(
            result.get("raw_hindi", result.get("raw_transcription", "N/A")),
            language="text",
        )

        st.markdown("**Hindi (corrected):**")
        st.code(result.get("corrected_hindi", "N/A"), language="text")

        st.markdown("**English translation:**")
        st.code(result.get("english_translation", "N/A"), language="text")
