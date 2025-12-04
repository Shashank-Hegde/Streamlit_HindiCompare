# streamlit.py
# Streamlit frontend to compare two Hindi ASR backends
# Each backend must expose POST /streamlitTranscribe

import io
import requests
import streamlit as st

# Your backend server
BACKEND_HOST = "49.200.100.22"        # or internal IP / hostname
MODEL_PORTS = [6004, 6005]            # FastAPI apps with /streamlitTranscribe
TIMEOUT_SEC = 180

st.set_page_config(page_title="Hindi ASR – Model Compare", layout="wide")

st.title("Hindi ASR – Compare Two Models")

st.caption(
    f"Audio is recorded in the browser and uploaded directly to FastAPI apps on "
    f"**{BACKEND_HOST}:{MODEL_PORTS[0]}** and **{BACKEND_HOST}:{MODEL_PORTS[1]}** "
    "via `/streamlitTranscribe`. The backend handles saving, VAD, ASR and translation."
)

st.markdown("---")

# -------------------- 1. Record Hindi audio --------------------
st.subheader("1. Record Hindi audio")

audio_file = st.audio_input(
    "Click to start recording, then click again to stop:",
    key="audio_rec",
)

if audio_file is None:
    st.info("👆 Record some audio to begin.")
    st.stop()

audio_bytes = audio_file.getvalue()
st.success("Audio captured.")
st.audio(audio_bytes, format="audio/wav")

st.markdown("---")
st.subheader("2. Send to models and view outputs")

if "results" not in st.session_state:
    st.session_state["results"] = None

col_btn, _ = st.columns([1, 3])

with col_btn:
    if st.button("Send to both models", type="primary"):
        results = {}
        for idx, port in enumerate(MODEL_PORTS, start=1):
            model_label = f"Model {idx} (port {port})"
            url = f"http://{BACKEND_HOST}:{port}/streamlitTranscribe"

            try:
                resp = requests.post(
                    url,
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

# -------------------- 3. Show results --------------------
st.markdown("---")
st.subheader("3. Model Outputs")

results = st.session_state.get("results")
if not results:
    st.info("Run inference first by clicking **Send to both models**.")
    st.stop()

# Make sure we always have exactly 2 columns
col1, col2 = st.columns(2)
cols = [col1, col2]

for (model_label, result), col in zip(results.items(), cols):
    with col:
        st.markdown(f"### {model_label}")

        if "error" in result:
            st.error(f"Request failed:\n\n`{result['error']}`")
            continue

        # Expected JSON keys from /streamlitTranscribe
        st.markdown(
            f"**Saved file on backend:** `{result.get('file', '?')}`  \n"
            f"**Duration (s):** `{result.get('audio_duration_seconds', '?')}`  \n"
            f"**Speech probability:** `{result.get('speech_probability', '?')}`"
        )

        st.markdown("**Hindi (raw):**")
        st.code(result.get("raw_hindi", "N/A"), language="text")

        st.markdown("**Hindi (corrected):**")
        st.code(result.get("corrected_hindi", "N/A"), language="text")

        st.markdown("**English translation:**")
        st.code(result.get("english_translation", "N/A"), language="text")
