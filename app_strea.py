import io
from datetime import datetime

import requests
import streamlit as st

BACKEND_HOST = "49.200.100.22"
MODEL_PORTS = [6004, 6005]  # FastAPI apps with /streamlitTranscribe
TIMEOUT_SEC = 180

st.set_page_config(page_title="Hindi ASR – Model Compare", layout="wide")

# ---------- Hide download button on audio elements (best-effort) ----------
HIDE_AUDIO_DOWNLOAD_CSS = """
<style>
audio::-webkit-media-controls-download-button {
    display: none !important;
}
audio::-webkit-media-controls-enclosure {
    overflow: hidden !important;
}
</style>
"""
st.markdown(HIDE_AUDIO_DOWNLOAD_CSS, unsafe_allow_html=True)

st.title("Hindi ASR – Compare Two Models")

st.caption(
    f"Speak in Hindi and a mixture of Hindi and English."
)

st.markdown("---")

# -------------------------------------------------------------------------
# 1. Provide Hindi audio (record or upload ONCE, then lock it)
# -------------------------------------------------------------------------

st.subheader("1. Provide Hindi audio")

if "final_audio_bytes" not in st.session_state:
    # No audio chosen yet → show input options
    input_method = st.radio(
        "Choose input method:",
        ["Record with microphone", "Upload WAV file"],
        index=0,
        key="audio_input_method",
    )

    audio_bytes_temp = None

    if input_method == "Record with microphone":
        audio_file = st.audio_input(
            "Click to record your Hindi audio, then click again to stop:",
            key="audio_rec",
        )
        if audio_file is not None:
            audio_bytes_temp = audio_file.getvalue()

    elif input_method == "Upload WAV file":
        uploaded_file = st.file_uploader(
            "Upload a .wav file with Hindi audio:",
            type=["wav"],
            key="audio_upload",
        )
        if uploaded_file is not None:
            audio_bytes_temp = uploaded_file.read()

    if audio_bytes_temp is None:
        if st.session_state.get("audio_input_method") == "Record with microphone":
            st.info("👆 Record some audio to begin.")
        else:
            st.info("👆 Upload a .wav file to begin.")
        st.stop()

    st.success("Audio captured. Preview below")
    st.audio(audio_bytes_temp, format="audio/wav")

    # Lock the audio so the recorder/uploader disappears on next run
    if st.button("Use this audio", type="primary"):
        st.session_state["final_audio_bytes"] = audio_bytes_temp
        st.experimental_rerun()

    st.stop()  # Wait until user clicks "Use this audio" before proceeding

# If we reach here, audio has been locked
audio_bytes = st.session_state["final_audio_bytes"]
st.success("Locked audio in use for both models.")

st.audio(audio_bytes, format="audio/wav")

# Optional: allow resetting the audio choice
if st.button("Reset audio and choose again"):
    for key in ["final_audio_bytes", "audio_input_method", "audio_rec", "audio_upload"]:
        if key in st.session_state:
            del st.session_state[key]
    st.experimental_rerun()

st.markdown("---")

# -------------------------------------------------------------------------
# 2. Send to models and view outputs
# -------------------------------------------------------------------------

st.subheader("2. Send to models and view outputs")

if "results" not in st.session_state:
    st.session_state["results"] = None

if "audio_label" not in st.session_state:
    st.session_state["audio_label"] = None

col_btn, _ = st.columns([1, 3])

with col_btn:
    if st.button("Send to both models", type="primary"):
        # Generate ONE shared filename for this audio
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        audio_label = f"streamlit_hindi_{ts}.wav"
        st.session_state["audio_label"] = audio_label

        results = {}
        for idx, port in enumerate(MODEL_PORTS, start=1):
            model_label = f"Model {idx} (port {port})"
            url = f"http://{BACKEND_HOST}:{port}/streamlitTranscribe"

            try:
                resp = requests.post(
                    url,
                    data={"client_filename": audio_label},
                    files={
                        "file": (
                            "recording.wav",
                            io.BytesIO(audio_bytes),
                            "audio/wav",
                        )
                    },
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

# -------------------------------------------------------------------------
# 3. Show results
# -------------------------------------------------------------------------

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

        if "error" in result:
            st.error(f"Request failed:\n\n`{result['error']}`")
            continue

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
