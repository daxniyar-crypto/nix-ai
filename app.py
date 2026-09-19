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
import io
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

try:
    from PIL import Image, ImageDraw
except Exception:
    Image = None
    ImageDraw = None


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
    "_raw_picked_image": None,         # bytes of a freshly picked photo, before editing
    "_marks": [],                      # colour-mark dots placed on the photo being edited
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
            font-size: 1.15rem;
            color: {title_color};
            margin: 0;
            padding-bottom: 0.9rem;
            margin-bottom: 1rem;
            border-bottom: 0.5px solid {card_border};
            font-weight: 500;
            letter-spacing: -0.01em;
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
            margin-bottom: 0.45rem;
        }}
        .chat-row.user {{
            justify-content: flex-start;
        }}
        .chat-row.assistant {{
            justify-content: flex-end;
        }}
        .chat-bubble {{
            max-width: 78%;
            padding: 0.55rem 0.85rem;
            border-radius: 14px;
            line-height: 1.5;
            font-size: 0.92rem;
            word-wrap: break-word;
        }}
        .chat-bubble.user {{
            background-color: #4169E1;
            border: 1px solid #3A5FCD;
            color: #ffffff;
            border-bottom-left-radius: 4px;
        }}
        .chat-bubble.assistant {{
            background-color: {btn_bg};
            border: 1px solid {btn_border};
            color: {fg};
            border-bottom-right-radius: 4px;
        }}
        .chat-bubble h1, .chat-bubble h2, .chat-bubble h3 {{
            font-size: 1.05rem;
            margin: 0.4rem 0 0.3rem 0;
            font-weight: 700 !important;
        }}
        .chat-bubble p {{ margin: 0.3rem 0; }}
        .chat-bubble ul, .chat-bubble ol {{ margin: 0.3rem 0; padding-left: 1.2rem; }}
        .chat-bubble strong {{ font-weight: 700; }}
        input, textarea {{
            background-color: {input_bg} !important;
            color: {fg} !important;
            border-color: {input_border} !important;
            border-radius: 8px !important;
        }}
        /* Chat input bar — rounded pill shape like Claude's app */
        [data-testid="stChatInput"] {{
            border-radius: 26px !important;
            border: 1px solid {card_border} !important;
            background-color: {card_bg} !important;
            padding: 2px 4px !important;
        }}
        [data-testid="stChatInput"] textarea {{
            background-color: transparent !important;
            border: none !important;
        }}
        /* Send button — swap Streamlit's default red for a theme-matched dark button */
        [data-testid="stChatInputSubmitButton"] {{
            background-color: {btn_bg} !important;
            border: 1px solid {btn_border} !important;
            border-radius: 50% !important;
        }}
        [data-testid="stChatInputSubmitButton"]:hover {{
            background-color: {btn_hover} !important;
        }}
        [data-testid="stChatInputSubmitButton"] svg {{
            fill: {fg} !important;
        }}
    </style>
    """, unsafe_allow_html=True)


inject_css(st.session_state.theme)

if st.session_state.logged_in and st.session_state.name:
    st.markdown(f"<h1 class='nix-title'>Heyy {st.session_state.name} 👋🏾</h1>", unsafe_allow_html=True)
else:
    st.markdown("<h1 class='nix-title'>NIX AI</h1>", unsafe_allow_html=True)


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


def _bubble_html(text: str, role: str, image_data_uri: str = None) -> str:
    """Wraps text in a styled chat-bubble div (right-aligned for assistant, left for user).
    Renders markdown (bold, headings, lists) instead of showing raw ** / ### symbols.
    If image_data_uri is given, shows the photo thumbnail above the text."""
    import html as _html
    safe = _html.escape(text) if text else ""
    img_html = (
        f'<img src="{image_data_uri}" style="max-width:100%;border-radius:10px;'
        f'display:block;margin-bottom:{"6px" if safe else "0"};">'
        if image_data_uri else ""
    )
    # Blank lines around the text let Streamlit's markdown parser render **bold**,
    # ### headings, and lists properly even though it's nested inside our div.
    return f'<div class="chat-row {role}"><div class="chat-bubble {role}">{img_html}\n\n{safe}\n\n</div></div>'


def _loading_bubble_html() -> str:
    """An assistant bubble with a bouncing 🚀 shown while waiting for a reply."""
    return (
        '<div class="chat-row assistant"><div class="chat-bubble assistant">'
        '<span class="nix-rocket">🚀</span>'
        '</div></div>'
        '<style>'
        '@keyframes nix-rocket-bounce {'
        '  0%, 100% { transform: translateY(0); }'
        '  50% { transform: translateY(-10px); }'
        '}'
        '.nix-rocket { display: inline-block; font-size: 1.4rem; '
        'animation: nix-rocket-bounce 0.7s ease-in-out infinite; }'
        '</style>'
    )


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
                stream_placeholder.markdown(_loading_bubble_html(), unsafe_allow_html=True)
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
