import streamlit as st
import requests
import time
import os

st.set_page_config(page_title="Hindi ASR – Port 6005", layout="centered")
st.title("🎙️ Hindi ASR Tester")
st.caption("Endpoint: `http://localhost:6005/streamlitTranscribe`")

ASR_URL = "http://localhost:6005/streamlitTranscribe"

uploaded = st.file_uploader("Upload WAV audio", type=["wav", "mp3", "m4a", "ogg", "webm"])

if uploaded:
    st.audio(uploaded, format=uploaded.type)

    if st.button("▶ Transcribe"):
        with st.spinner("Sending to Hindi ASR (port 6005)…"):
            try:
                t_start = time.time()
                resp = requests.post(
                    ASR_URL,
                    files={"file": (uploaded.name, uploaded.getvalue(), uploaded.type)},
                    data={"client_filename": uploaded.name},
                    timeout=120,
                )
                elapsed = time.time() - t_start

                if resp.status_code == 200:
                    j = resp.json()

                    st.success(f"✅ Done in **{elapsed:.2f}s**")

                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Audio Duration (s)",
                                  f"{j.get('audio_duration_seconds', 'N/A'):.2f}"
                                  if isinstance(j.get('audio_duration_seconds'), (int, float))
                                  else "N/A")
                    with col2:
                        st.metric("API Round-trip (s)", f"{elapsed:.2f}")

                    st.divider()

                    st.subheader("🔤 Raw Hindi")
                    st.text_area("raw_hindi", value=j.get("raw_hindi", ""), height=80,
                                 label_visibility="collapsed")

                    st.subheader("✏️ Corrected Hindi")
                    st.text_area("corrected_hindi", value=j.get("corrected_hindi", ""), height=80,
                                 label_visibility="collapsed")

                    st.subheader("🌐 English Translation")
                    st.text_area("english_translation", value=j.get("english_translation", ""), height=80,
                                 label_visibility="collapsed")

                    with st.expander("Full JSON response"):
                        st.json(j)

                else:
                    st.error(f"HTTP {resp.status_code}: {resp.text}")

            except requests.exceptions.ConnectionError:
                st.error("❌ Could not connect to port 6005. Is the service running?")
            except requests.exceptions.Timeout:
                st.error("❌ Request timed out (>120s).")
            except Exception as e:
                st.error(f"❌ Unexpected error: {e}")
