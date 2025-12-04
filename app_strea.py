import os
import uuid
from datetime import datetime

import requests
import streamlit as st

# ===========================
# CONFIG
# ===========================

# Unified audio directory for both Streamlit and ASR apps
AUDIO_BASE = os.path.expanduser("~/Streamlit/Audio/Hindi")

# Backend H200 server
BACKEND_HOST = "http://49.200.100.22"

# Two ASR model endpoints
MODEL_ENDPOINTS = {
    "Model 1 (port 6004)": f"{BACKEND_HOST}:6004/convertSpeechToText",
    "Model 2 (port 6005)": f"{BACKEND_HOST}:6005/convertSpeechToText",
}


# ===========================
# HELPERS
# ===========================

def ensure_dirs():
    """Create the unified audio directory if it doesn't exist."""
    os.makedirs(AUDIO_BASE, exist_ok=True)


def save_audio_file(audio_bytes: bytes) -> str:
    """
    Save recorded audio into the unified folder:
        ~/Streamlit/Audio/Hindi

    Returns:
        filename (str): The filename only (not the full path),
                        which will be passed to the ASR APIs.
    """
    ensure_dirs()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid = uuid.uuid4().hex[:6]
    filename = f"hindi_rec_{ts}_{uid}.wav"

    full_path = os.path.join(AUDIO_BASE, filename)
    with open(full_path, "wb") as f:
        f.write(audio_bytes)

    return filename


def call_model(endpoint: str, audio_filename: str):
    """
    Call a single ASR FastAPI model's /convertSpeechToText endpoint.

    The ASR app is expected to read from the unified folder:
        VOICE_REQUEST_DIR = ~/Streamlit/Audio/Hindi

    Args:
        endpoint (str): Full URL of the FastAPI endpoint.
        audio_filename (str): Name of the file saved in AUDIO_BASE.

    Returns:
        dict: Parsed / simplified model response.
    """
    payload = {
        "audioFileName": audio_filename,
        "new_session_data": {},  # they default safely if this is empty
    }

    try:
        resp = requests.post(endpoint, json=payload, timeout=300)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        return {"error": f"Request failed: {e}"}

    try:
        data = resp.json()
    except ValueError:
        return {"error": "Could not decode JSON from model response"}

    results = data.get("results", [])
    if not results:
        return {"error": "No results returned by model", "raw": data}

    r0 = results[0]

    return {
        "status": r0.get("status", "unknown"),
        "raw_hindi": r0.get("raw_transcription", ""),
        "corrected_hindi": r0.get("corrected_hindi", ""),
        "english": r0.get("english_translation", ""),
        "audio_duration": r0.get("audio_duration_seconds"),
        "speech_probability": r0.get("speech_probability"),
        "full_raw_response": data,
    }


# ===========================
# STREAMLIT UI
# ===========================

st.set_page_config(
    page_title="Hindi ASR Comparator",
    layout="centered",
)

st.title("🎙 Hindi ASR & Translation – Model Comparison")

st.markdown(
    """
1. Record a Hindi audio clip using your mic.  
2. The audio is stored on the server at `~/Streamlit/Audio/Hindi`.  
3. The same file is sent to **two ASR+translation models** running on ports **6004** and **6005**.  
4. Their outputs are displayed side-by-side for comparison.
"""
)

st.info(
    "Make sure your FastAPI apps (`apphi1.py` and `apphi2.py`) are running on "
    "`49.200.100.22:6004` and `:6005` and are configured to read audio from "
    "`~/Streamlit/Audio/Hindi`."
)

# Audio recording widget
audio_file = st.audio_input("Click to record your Hindi audio, then click again to stop:")

if audio_file is None:
    st.write("👆 Record some audio to begin.")
else:
    st.success("Audio captured.")

    # Optional playback preview
    st.audio(audio_file)

    if st.button("Send to both models"):
        audio_bytes = audio_file.getbuffer()

        with st.spinner("Saving audio and contacting both models..."):
            # Save once to the unified folder
            try:
                filename = save_audio_file(audio_bytes)
            except Exception as e:
                st.error(f"Failed to save audio on server: {e}")
                st.stop()

            st.caption(f"Saved audio file: `{filename}` in `~/Streamlit/Audio/Hindi`")

            # Call both endpoints
            model_outputs = {}
            for model_name, endpoint in MODEL_ENDPOINTS.items():
                model_outputs[model_name] = call_model(endpoint, filename)

        st.subheader("Model Outputs")

        # Display results side-by-side
        col1, col2 = st.columns(2)

        for col, (model_name, result) in zip((col1, col2), model_outputs.items()):
            with col:
                st.markdown(f"### {model_name}")

                if "error" in result:
                    st.error(result["error"])
                    if "raw" in result:
                        with st.expander("Raw response"):
                            st.json(result["raw"])
                    continue

                st.markdown("**Status:** " + str(result.get("status", "unknown")))

                dur = result.get("audio_duration")
                sp = result.get("speech_probability")
                if dur is not None or sp is not None:
                    st.caption(
                        f"Duration: {dur:.2f} s | Speech probability: {sp:.3f}"
                        if dur is not None and sp is not None
                        else f"Duration: {dur} s"
                        if dur is not None
                        else f"Speech prob: {sp}"
                    )

                st.markdown("**Raw Hindi transcript:**")
                st.write(result.get("raw_hindi", ""))

                st.markdown("**Corrected Hindi transcript:**")
                st.write(result.get("corrected_hindi", ""))

                st.markdown("**English translation:**")
                st.write(result.get("english", ""))

                with st.expander("Full JSON response"):
                    st.json(result.get("full_raw_response", {}))
