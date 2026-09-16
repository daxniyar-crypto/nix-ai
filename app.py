"""
NIX AI — Professional Gen-Z Minimalist Assistant (UI/UX Upgraded)
-------------------------------------------------------------------
Upgrades in this version:
  1. Streaming replies (typewriter effect) instead of one-shot text
  2. Chat avatars for user / assistant
  3. Light / Dark theme toggle (persisted in session)
"""

import streamlit as st
import random
import time

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
    import docx
except ImportError:
    docx = None

try:
    from google import genai
except ImportError:
    genai = None


# ---------------------------------------------------------------------
# CONFIG & API SETUP
# ---------------------------------------------------------------------
try:
    API_KEY = st.secrets["API_KEY"]
except Exception:
    API_KEY = ""
MODEL_NAME = "gemini-3.6-flash"  # stable, widely available; change if you have access to a newer model
OTP_VALID_SECONDS = 300  # 5 min
USER_AVATAR = "🧑"
BOT_AVATAR = "⚡"

st.set_page_config(page_title="NIX AI", page_icon="⚡", layout="centered")

client = None
if genai and API_KEY :
    try:
        client = genai.Client(api_key=API_KEY)
    except Exception:
        client = None


# ---------------------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------------------
defaults = {
    "logged_in": False,
    "otp": None,
    "otp_time": None,
    "phone": "",
    "otp_sent": False,
    "messages": [],
    "doc_text": "",
    "doc_name": "",
    "theme": "dark",   # NEW: theme toggle state
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val


# ---------------------------------------------------------------------
# THEME CSS (dark / light)
# ---------------------------------------------------------------------
def inject_css(theme: str):
    if theme == "dark":
        bg, fg, sub = "#0b0f19", "#e2e8f0", "#94a3b8"
        card_bg, card_border = "#111827", "#1f2937"
        input_bg, input_border = "#111827", "#374151"
        btn_bg, btn_border, btn_hover = "#1e293b", "#334155", "#334155"
        sidebar_bg, sidebar_border = "#0f172a", "#1e293b"
        title_color = "#ffffff"
    else:
        bg, fg, sub = "#f8fafc", "#0f172a", "#64748b"
        card_bg, card_border = "#ffffff", "#e2e8f0"
        input_bg, input_border = "#ffffff", "#cbd5e1"
        btn_bg, btn_border, btn_hover = "#e2e8f0", "#cbd5e1", "#cbd5e1"
        sidebar_bg, sidebar_border = "#f1f5f9", "#e2e8f0"
        title_color = "#0b0f19"

    st.markdown(f"""
    <style>
        .stApp {{
            background-color: {bg};
            color: {fg};
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        }}
        h1, h2, h3 {{
            font-weight: 700 !important;
            letter-spacing: -0.025em;
        }}
        .nix-title {{
            text-align: center;
            font-size: 2.5rem;
            color: {title_color};
            margin-bottom: 0;
            font-weight: 800;
        }}
        .nix-sub {{
            text-align: center;
            color: {sub};
            font-size: 0.95rem;
            margin-top: 4px;
            margin-bottom: 2rem;
            letter-spacing: 0.05em;
        }}
        div.stButton > button {{
            background: {btn_bg};
            color: {fg};
            border: 1px solid {btn_border};
            border-radius: 8px;
            padding: 0.5rem 1.2rem;
            font-weight: 600;
            transition: all 0.2s ease;
        }}
        div.stButton > button:hover {{
            background: {btn_hover};
            border-color: {btn_border};
        }}
        section[data-testid="stSidebar"] {{
            background-color: {sidebar_bg};
            border-right: 1px solid {sidebar_border};
        }}
        .stChatMessage {{
            background-color: {card_bg};
            border: 1px solid {card_border};
            border-radius: 12px;
            padding: 1rem;
        }}
        input, textarea {{
            background-color: {input_bg} !important;
            color: {fg} !important;
            border-color: {input_border} !important;
            border-radius: 8px !important;
        }}
    </style>
    """, unsafe_allow_html=True)


inject_css(st.session_state.theme)

st.markdown("<h1 class='nix-title'>NIX AI</h1>", unsafe_allow_html=True)
st.markdown("<p class='nix-sub'>MINIMAL INTELLIGENCE // SECURE & FAST</p>", unsafe_allow_html=True)


# ---------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------
def generate_otp():
    return str(random.randint(100000, 999999))


def extract_text(uploaded_file):
    name = uploaded_file.name.lower()
    try:
        if name.endswith(".txt"):
            return uploaded_file.read().decode("utf-8", errors="ignore")
        elif name.endswith(".pdf"):
            if PyPDF2 is None:
                return None
            reader = PyPDF2.PdfReader(uploaded_file)
            return "".join((page.extract_text() or "") + "\n" for page in reader.pages)
        elif name.endswith(".docx"):
            if docx is None:
                return None
            d = docx.Document(uploaded_file)
            return "\n".join(p.text for p in d.paragraphs)
        return None
    except Exception:
        return None


def _with_retry(fn, max_attempts=4, base_delay=1.0):
    """
    Runs fn() with automatic retries on transient errors (503 overloaded,
    429 rate-limited, timeouts, connection resets). Uses exponential backoff
    so a busy Gemini server doesn't kill the demo — it just quietly retries.
    Raises the last exception if all attempts fail.
    """
    transient_markers = ["503", "overloaded", "429", "rate limit", "timeout",
                          "unavailable", "deadline", "connection reset", "temporarily"]
    last_err = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            last_err = e
            err_text = str(e).lower()
            is_transient = any(marker in err_text for marker in transient_markers)
            if not is_transient or attempt == max_attempts - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))  # 1s, 2s, 4s, ...
    raise last_err


def _typewriter(text: str, delay: float = 0.012):
    """Generator that yields the reply word by word for a streaming/typewriter effect."""
    words = text.split(" ")
    buf = ""
    for i, w in enumerate(words):
        buf += (" " if i > 0 else "") + w
        yield buf
        time.sleep(delay)


def ask_ai(prompt, system_context="", stream_placeholder=None):
    """
    Calls Gemini. If the SDK supports streaming (generate_content_stream), uses it
    for real token-by-token output. Otherwise falls back to a typewriter effect
    over the full response so the UI still feels alive.
    Returns the final full text.
    """
    if client is None:
        msg = "⚠️ Please update `API_KEY` in the code with a valid Gemini key from Google AI Studio (starts with `AQ.` or `AIzaSy`)!"
        if stream_placeholder:
            stream_placeholder.markdown(msg)
        return msg

    # Build a plain-text transcript for context (used by both API paths below)
    transcript = ""
    for m in st.session_state.messages[:-1]:
        speaker = "User" if m["role"] == "user" else "Assistant"
        transcript += f"{speaker}: {m['content']}\n"

    full_prompt = ""
    if system_context:
        full_prompt += f"Context:\n{system_context}\n\n"
    if transcript:
        full_prompt += f"Conversation so far:\n{transcript}\n"
    full_prompt += f"User: {prompt}"

    # --- Path 1: Interactions API (recommended for new "AQ." auth keys) ---
    try:
        if hasattr(client, "interactions"):
            if stream_placeholder:
                stream_placeholder.markdown("⏳ Connecting...")
            result = _with_retry(lambda: client.interactions.create(model=MODEL_NAME, input=full_prompt))
            text = result.output_text
            if stream_placeholder:
                for partial in _typewriter(text):
                    stream_placeholder.markdown(partial + "▌")
                stream_placeholder.markdown(text)
            return text
    except Exception:
        pass  # fall through to legacy path below (e.g. older SDK, legacy AIzaSy key)

    # --- Path 2: legacy models.generate_content (works with older AIzaSy keys) ---
    history_formatted = [
        {
            "role": "user" if m["role"] == "user" else "model",
            "parts": [{"text": m["content"]}],
        }
        for m in st.session_state.messages[:-1]
    ]
    contents = history_formatted + [{"role": "user", "parts": [{"text": full_prompt}]}]

    try:
        if hasattr(client.models, "generate_content_stream"):
            def _run_stream():
                collected = ""
                for chunk in client.models.generate_content_stream(model=MODEL_NAME, contents=contents):
                    piece = getattr(chunk, "text", "") or ""
                    collected += piece
                    if stream_placeholder:
                        stream_placeholder.markdown(collected + "▌")
                return collected
            collected = _with_retry(_run_stream)
            if stream_placeholder:
                stream_placeholder.markdown(collected)
            return collected
    except Exception:
        pass

    try:
        response = _with_retry(lambda: client.models.generate_content(model=MODEL_NAME, contents=contents))
        text = response.text
        if stream_placeholder:
            for partial in _typewriter(text):
                stream_placeholder.markdown(partial + "▌")
            stream_placeholder.markdown(text)
        return text
    except Exception as e:
        # Friendly message instead of a raw stack trace / error code —
        # so a demo never shows something scary like "503" on screen.
        err_text = str(e).lower()
        if any(m in err_text for m in ["503", "overloaded", "unavailable"]):
            err = "⚠️ Gemini's servers are busy right now. Please try again in a few seconds."
        elif "429" in err_text or "rate limit" in err_text:
            err = "⚠️ Too many requests right now — please wait a moment and try again."
        elif "401" in err_text or "unauthenticated" in err_text or "invalid" in err_text:
            err = "⚠️ API key issue — please check the key in Settings/Secrets."
        else:
            err = f"⚠️ Something went wrong talking to Gemini: {e}"
        if stream_placeholder:
            stream_placeholder.markdown(err)
        return err


# ---------------------------------------------------------------------
# LOGIN PAGE
# ---------------------------------------------------------------------
def login_page():
    st.subheader("Authentication")
    st.markdown("<p style='font-size: 0.85rem; opacity: 0.7;'>Enter your mobile number to initialize session.</p>", unsafe_allow_html=True)

    if not st.session_state.otp_sent:
        phone = st.text_input("Phone Number", max_chars=10, placeholder="9876543210")
        if st.button("Generate OTP"):
            if phone.isdigit() and len(phone) == 10:
                st.session_state.phone = phone
                st.session_state.otp = generate_otp()
                st.session_state.otp_time = time.time()
                st.session_state.otp_sent = True
                st.rerun()
            else:
                st.error("Please enter a valid 10-digit number.")
    else:
        st.info(f"OTP dispatched to +91 {st.session_state.phone}")
        st.success(f"Development OTP: {st.session_state.otp}")

        entered = st.text_input("Enter 6-digit OTP", max_chars=6)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Verify"):
                if time.time() - st.session_state.otp_time > OTP_VALID_SECONDS:
                    st.error("OTP expired. Please resend.")
                    st.session_state.otp_sent = False
                elif entered == st.session_state.otp:
                    st.session_state.logged_in = True
                    st.rerun()
                else:
                    st.error("Invalid OTP.")
        with col2:
            if st.button("Resend OTP"):
                st.session_state.otp = generate_otp()
                st.session_state.otp_time = time.time()
                st.rerun()


# ---------------------------------------------------------------------
# MAIN APP
# ---------------------------------------------------------------------
def main_app():
    with st.sidebar:
        # NEW: theme toggle
        st.subheader("Appearance")
        theme_choice = st.radio(
            "Theme", ["dark", "light"],
            index=0 if st.session_state.theme == "dark" else 1,
            horizontal=True,
        )
        if theme_choice != st.session_state.theme:
            st.session_state.theme = theme_choice
            st.rerun()

        st.markdown("---")
        st.subheader("Document Context")
        uploaded = st.file_uploader("Upload reference file", type=["txt", "pdf", "docx"])

        if uploaded is not None:
            text = extract_text(uploaded)
            if text:
                st.session_state.doc_text = text
                st.session_state.doc_name = uploaded.name
                st.success(f"Loaded: {uploaded.name} ({len(text)} chars)")
                if st.button("Summarize Document"):
                    with st.spinner("Analyzing document..."):
                        summary_placeholder = st.empty()
                        ask_ai(
                            "Provide a clean, concise summary of this document in bullet points:",
                            system_context=text[:12000],
                            stream_placeholder=summary_placeholder,
                        )
            else:
                st.error("Failed to parse file.")

        st.markdown("---")
        if st.button("Terminate Session"):
            for k, v in defaults.items():
                st.session_state[k] = v
            st.rerun()

    # Render chat history with avatars
    for msg in st.session_state.messages:
        avatar = USER_AVATAR if msg["role"] == "user" else BOT_AVATAR
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

    user_input = st.chat_input("Type a message or query...")
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar=USER_AVATAR):
            st.markdown(user_input)

        with st.chat_message("assistant", avatar=BOT_AVATAR):
            placeholder = st.empty()
            with st.spinner("Thinking..."):
                context = ""
                if st.session_state.doc_text:
                    context = f"Reference Document:\n{st.session_state.doc_text[:8000]}"
                reply = ask_ai(user_input, system_context=context, stream_placeholder=placeholder)

        st.session_state.messages.append({"role": "assistant", "content": reply})


# ---------------------------------------------------------------------
# ROUTING
# ---------------------------------------------------------------------
if not st.session_state.logged_in:
    login_page()
else:
    main_app()
