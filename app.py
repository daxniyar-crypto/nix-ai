"""
NIX AI — Professional Gen-Z Minimalist Assistant (UI/UX Upgraded)
-------------------------------------------------------------------
Upgrades in this version:
  1. Streaming replies (typewriter effect) instead of one-shot text
  2. Custom chat bubbles, no avatars/icons — user messages left, AI replies right
  3. Light / Dark theme toggle (persisted in session)
  4. Automatic retry on transient errors (503 / 429 / timeouts)
  5. Name field at login + personalized "Heyy [naam] 👋🏾" greeting
  6. Camera / gallery image upload — ask questions about a photo (Gemini vision)
  7. Persistent chat history + multiple conversations, saved via Supabase
"""

import streamlit as st
import random
import time
import base64
import urllib.parse

try:
    import PyPDF2
except Exception:
    PyPDF2 = None

try:
    import docx
except Exception:
    docx = None

try:
    from google import genai
except Exception:
    genai = None

try:
    from supabase import create_client
except Exception:
    create_client = None


# ---------------------------------------------------------------------
# CONFIG & API SETUP
# ---------------------------------------------------------------------
try:
    API_KEY = st.secrets["API_KEY"]
except Exception:
    API_KEY = ""
MODEL_NAME = "gemini-3.6-flash"  # current model; gemini-2.5-flash is no longer available to new users
OTP_VALID_SECONDS = 300  # 5 min

st.set_page_config(page_title="NIX AI", page_icon="⚡", layout="centered")

client = None
if genai and API_KEY and API_KEY != "APNI_ASLI_KEY_YAHAN_PASTE_KAR_DENA":
    try:
        client = genai.Client(api_key=API_KEY)
    except Exception:
        client = None

# --- Supabase (for persistent chat history) ---
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
except Exception:
    SUPABASE_URL = ""
try:
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
except Exception:
    SUPABASE_KEY = ""

sb = None
if create_client and SUPABASE_URL and SUPABASE_KEY:
    try:
        sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        sb = None


def db_available():
    return sb is not None


def db_create_conversation(phone, name, title):
    if not db_available():
        return None
    try:
        res = sb.table("conversations").insert(
            {"phone": phone, "name": name, "title": title}
        ).execute()
        return res.data[0]["id"] if res.data else None
    except Exception:
        return None


def db_list_conversations(phone):
    if not db_available():
        return []
    try:
        res = (
            sb.table("conversations")
            .select("*")
            .eq("phone", phone)
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception:
        return []


def db_load_messages(conversation_id):
    if not db_available():
        return []
    try:
        res = (
            sb.table("messages")
            .select("*")
            .eq("conversation_id", conversation_id)
            .order("created_at")
            .execute()
        )
        return [{"role": m["role"], "content": m["content"]} for m in (res.data or [])]
    except Exception:
        return []


def db_save_message(conversation_id, role, content):
    if not db_available() or not conversation_id:
        return
    try:
        sb.table("messages").insert(
            {"conversation_id": conversation_id, "role": role, "content": content}
        ).execute()
    except Exception:
        pass


def db_delete_conversation(conversation_id):
    if not db_available() or not conversation_id:
        return
    try:
        sb.table("messages").delete().eq("conversation_id", conversation_id).execute()
        sb.table("conversations").delete().eq("id", conversation_id).execute()
    except Exception:
        pass


# ---------------------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------------------
defaults = {
    "logged_in": False,
    "otp": None,
    "otp_time": None,
    "phone": "",
    "name": "",
    "otp_sent": False,
    "messages": [],
    "doc_text": "",
    "doc_name": "",
    "theme": "dark",              # theme toggle state
    "current_conversation_id": None,   # active conversation in Supabase
    "pending_image": None,             # bytes of an image waiting to be asked about
    "pending_image_mime": None,
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
        /* Custom chat bubbles: user on the left, assistant on the right, no avatars */
        .chat-row {{
            display: flex;
            width: 100%;
            margin-bottom: 0.6rem;
        }}
        .chat-row.user {{
            justify-content: flex-start;
        }}
        .chat-row.assistant {{
            justify-content: flex-end;
        }}
        .chat-bubble {{
            max-width: 78%;
            padding: 0.7rem 1rem;
            border-radius: 14px;
            line-height: 1.5;
            word-wrap: break-word;
        }}
        .chat-bubble.user {{
            background-color: {card_bg};
            border: 1px solid {card_border};
            color: {fg};
            border-bottom-left-radius: 4px;
        }}
        .chat-bubble.assistant {{
            background-color: {btn_bg};
            border: 1px solid {btn_border};
            color: {fg};
            border-bottom-right-radius: 4px;
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

if st.session_state.logged_in and st.session_state.name:
    st.markdown(f"<h1 class='nix-title'>Heyy {st.session_state.name} 👋🏾</h1>", unsafe_allow_html=True)
else:
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


def _bubble_html(text: str, role: str) -> str:
    """Wraps text in a styled chat-bubble div (right-aligned for assistant, left for user)."""
    import html as _html
    safe = _html.escape(text).replace("\n", "<br>")
    return f'<div class="chat-row {role}"><div class="chat-bubble {role}">{safe}</div></div>'


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
            stream_placeholder.markdown(_bubble_html(msg, "assistant"), unsafe_allow_html=True)
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
                stream_placeholder.markdown(_bubble_html("⏳ Connecting...", "assistant"), unsafe_allow_html=True)
            result = _with_retry(lambda: client.interactions.create(model=MODEL_NAME, input=full_prompt))
            text = result.output_text
            if stream_placeholder:
                for partial in _typewriter(text):
                    stream_placeholder.markdown(_bubble_html(partial + "▌", "assistant"), unsafe_allow_html=True)
                stream_placeholder.markdown(_bubble_html(text, "assistant"), unsafe_allow_html=True)
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
                        stream_placeholder.markdown(_bubble_html(collected + "▌", "assistant"), unsafe_allow_html=True)
                return collected
            collected = _with_retry(_run_stream)
            if stream_placeholder:
                stream_placeholder.markdown(_bubble_html(collected, "assistant"), unsafe_allow_html=True)
            return collected
    except Exception:
        pass

    try:
        response = _with_retry(lambda: client.models.generate_content(model=MODEL_NAME, contents=contents))
        text = response.text
        if stream_placeholder:
            for partial in _typewriter(text):
                stream_placeholder.markdown(_bubble_html(partial + "▌", "assistant"), unsafe_allow_html=True)
            stream_placeholder.markdown(_bubble_html(text, "assistant"), unsafe_allow_html=True)
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
            stream_placeholder.markdown(_bubble_html(err, "assistant"), unsafe_allow_html=True)
        return err


def ask_ai_vision(prompt, image_bytes, mime_type="image/jpeg", stream_placeholder=None):
    """Sends a photo + question to Gemini (vision) and returns the answer."""
    if client is None:
        msg = "⚠️ Please update `API_KEY` in the code with a valid Gemini key from Google AI Studio (starts with `AQ.` or `AIzaSy`)!"
        if stream_placeholder:
            stream_placeholder.markdown(_bubble_html(msg, "assistant"), unsafe_allow_html=True)
        return msg

    b64 = base64.b64encode(image_bytes).decode("utf-8")
    contents = [{
        "role": "user",
        "parts": [
            {"text": prompt or "Describe this image and answer any question in it."},
            {"inline_data": {"mime_type": mime_type, "data": b64}},
        ],
    }]

    try:
        response = _with_retry(lambda: client.models.generate_content(model=MODEL_NAME, contents=contents))
        text = response.text
        if stream_placeholder:
            for partial in _typewriter(text):
                stream_placeholder.markdown(_bubble_html(partial + "▌", "assistant"), unsafe_allow_html=True)
            stream_placeholder.markdown(_bubble_html(text, "assistant"), unsafe_allow_html=True)
        return text
    except Exception as e:
        err_text = str(e).lower()
        if any(m in err_text for m in ["503", "overloaded", "unavailable"]):
            err = "⚠️ Gemini's servers are busy right now. Please try again in a few seconds."
        elif "429" in err_text or "rate limit" in err_text:
            err = "⚠️ Too many requests right now — please wait a moment and try again."
        else:
            err = f"⚠️ Couldn't analyze the image: {e}"
        if stream_placeholder:
            stream_placeholder.markdown(_bubble_html(err, "assistant"), unsafe_allow_html=True)
        return err


# ---------------------------------------------------------------------
# LOGIN PAGE
# ---------------------------------------------------------------------
def login_page():
    st.subheader("Authentication")
    st.markdown("<p style='font-size: 0.85rem; opacity: 0.7;'>Enter your mobile number to initialize session.</p>", unsafe_allow_html=True)

    if not st.session_state.otp_sent:
        name = st.text_input("Your Name", placeholder="e.g. Rohan")
        phone = st.text_input("Phone Number", max_chars=10, placeholder="9876543210")
        if st.button("Generate OTP"):
            if not name.strip():
                st.error("Please enter your name.")
            elif phone.isdigit() and len(phone) == 10:
                st.session_state.name = name.strip()
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

    # --- Help / contact section ---
    whatsapp_number = "918822166691"  # +91 8822166691, no "+" or spaces for wa.me links
    whatsapp_message = "Hey Niyar, I need help with NIX AI 🙏"
    wa_link = f"https://wa.me/{whatsapp_number}?text={urllib.parse.quote(whatsapp_message)}"

    st.markdown(f"""
    <div style='text-align:center; font-size:0.8rem; opacity:0.65; margin-top:2.5rem; line-height:1.6;'>
        For any kind of help, contact us —<br>
        <a href="mailto:niyardaxx@gmail.com" style="color:inherit; text-decoration:underline;">niyardaxx@gmail.com</a>
        &nbsp;or&nbsp;
        <a href="{wa_link}" target="_blank" style="color:inherit; text-decoration:underline;">+91 88221 66691</a>
    </div>
    """, unsafe_allow_html=True)


# ---------------------------------------------------------------------
# MAIN APP
# ---------------------------------------------------------------------
def main_app():
    with st.sidebar:
        # --- Chat history: new chat + past conversations ---
        st.subheader("Chats")
        if st.button("➕ New Chat"):
            st.session_state.messages = []
            st.session_state.current_conversation_id = None
            st.rerun()

        if db_available():
            convos = db_list_conversations(st.session_state.phone)
            if not convos:
                st.caption("No past chats yet.")
            for c in convos:
                label = c.get("title") or "Untitled chat"
                is_active = c["id"] == st.session_state.current_conversation_id
                if st.button(("• " if is_active else "") + label, key=f"conv_{c['id']}"):
                    st.session_state.current_conversation_id = c["id"]
                    st.session_state.messages = db_load_messages(c["id"])
                    st.rerun()
        else:
            st.caption("Chat history needs Supabase SUPABASE_URL / SUPABASE_KEY in Secrets.")

        st.markdown("---")

        # --- Theme toggle ---
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
                        st.markdown("### Summary")
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

    # Render chat history as bubbles: user on the left, assistant on the right, no avatars/icons
    for msg in st.session_state.messages:
        st.markdown(_bubble_html(msg["content"], msg["role"]), unsafe_allow_html=True)

    # Message box with a built-in attach icon (📎) — tapping it on mobile opens
    # the phone's own Camera / Photo Library picker, just like a normal chat app.
    user_input = st.chat_input(
        "Type a message or query...",
        accept_file=True,
        file_type=["jpg", "jpeg", "png"],
    )

    if user_input:
        text = (user_input.text or "").strip()
        files = user_input.files or []

        # Create a conversation in Supabase on the first message of a new chat
        if st.session_state.current_conversation_id is None and db_available():
            title = (text or "Photo question")[:40]
            st.session_state.current_conversation_id = db_create_conversation(
                st.session_state.phone, st.session_state.name, title
            )

        display_text = text if text else "📷 [photo]"
        st.session_state.messages.append({"role": "user", "content": display_text})
        st.markdown(_bubble_html(display_text, "user"), unsafe_allow_html=True)
        db_save_message(st.session_state.current_conversation_id, "user", display_text)

        placeholder = st.empty()

        if files:
            image_file = files[0]
            reply = ask_ai_vision(
                text or "Describe this image and answer any question in it.",
                image_file.getvalue(),
                image_file.type or "image/jpeg",
                stream_placeholder=placeholder,
            )
        else:
            context = ""
            if st.session_state.doc_text:
                context = f"Reference Document:\n{st.session_state.doc_text[:8000]}"
            reply = ask_ai(text, system_context=context, stream_placeholder=placeholder)

        st.session_state.messages.append({"role": "assistant", "content": reply})
        db_save_message(st.session_state.current_conversation_id, "assistant", reply)


# ---------------------------------------------------------------------
# ROUTING
# ---------------------------------------------------------------------
if not st.session_state.logged_in:
    login_page()
else:
    main_app()
