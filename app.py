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
import streamlit.components.v1 as components
import json
from datetime import datetime, timedelta, timezone
import random
import re
import html as _html_lib
import time
import base64
import io
import hashlib
import secrets
import string
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
ADMIN_PHONES = {"8822166691"}  # owner number(s) allowed to open the admin dashboard
try:
    DAILY_MESSAGE_CAP = int(st.secrets["DAILY_CAP"])  # change it in Secrets, no code edit needed
except Exception:
    DAILY_MESSAGE_CAP = 30  # messages per person per day; the owner is exempt

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


def db_rename_conversation(conversation_id, new_title):
    if not db_available() or not conversation_id or not new_title:
        return
    try:
        sb.table("conversations").update({"title": new_title}).eq("id", conversation_id).execute()
    except Exception:
        pass


def db_admin_stats():
    """Totals only for the owner dashboard — never returns chat content."""
    stats = {"users": None, "conversations": None, "messages": None, "recent_users": []}
    if not db_available():
        return stats
    try:
        for table in ("users", "conversations", "messages"):
            res = sb.table(table).select("id", count="exact").limit(1).execute()
            stats[table] = res.count
        res = (
            sb.table("users")
            .select("name,phone,created_at")
            .order("created_at", desc=True)
            .limit(10)
            .execute()
        )
        stats["recent_users"] = res.data or []
    except Exception:
        pass
    return stats


_IST = timezone(timedelta(hours=5, minutes=30))


def _today_ist() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _ist_midnight_utc() -> str:
    """Start of today in IST, written as a UTC timestamp the database understands."""
    start = datetime.now(_IST).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def db_count_user_messages_today(phone):
    """Messages this person has sent since midnight IST. None if it can't be checked."""
    if not db_available():
        return None
    try:
        convs = (
            sb.table("conversations").select("id").eq("phone", phone)
            .order("created_at", desc=True).limit(200).execute().data or []
        )
        ids = [c["id"] for c in convs]
        if not ids:
            return 0
        res = (
            sb.table("messages").select("id", count="exact")
            .in_("conversation_id", ids).eq("role", "user")
            .gte("created_at", _ist_midnight_utc()).limit(1).execute()
        )
        return res.count or 0
    except Exception:
        return None


def daily_cap_for(phone):
    """None means unlimited (the owner)."""
    return None if phone in ADMIN_PHONES else DAILY_MESSAGE_CAP


def messages_used_today(phone, refresh=False):
    """Today's count, cached per session. refresh=True re-reads it from the database."""
    today = _today_ist()
    cache = st.session_state.get("_cap_cache")
    same = bool(cache) and cache.get("day") == today and cache.get("phone") == phone
    if refresh or not same:
        n = db_count_user_messages_today(phone)
        if n is None:  # database hiccup: don't lock anyone out, keep the last known number
            n = cache["used"] if same else 0
        st.session_state._cap_cache = {"day": today, "phone": phone, "used": n}
    return st.session_state._cap_cache["used"]


def _bump_cap_cache():
    cache = st.session_state.get("_cap_cache")
    if cache and cache.get("day") == _today_ist():
        cache["used"] += 1


def within_daily_cap():
    """True if the signed-in person can send another message. Shows a notice if not."""
    phone = st.session_state.phone
    cap = daily_cap_for(phone)
    if cap is None:
        return True
    if messages_used_today(phone, refresh=True) >= cap:
        st.warning(f"You've used all {cap} messages for today. Your limit resets at 12:00 AM IST.")
        return False
    return True


def db_get_user(phone):
    if not db_available():
        return None
    try:
        res = sb.table("users").select("*").eq("phone", phone).execute()
        return res.data[0] if res.data else None
    except Exception:
        return None


def db_create_user(phone, name, password_hash):
    if not db_available():
        return None
    try:
        res = sb.table("users").insert(
            {"phone": phone, "name": name, "password_hash": password_hash}
        ).execute()
        return res.data[0] if res.data else None
    except Exception:
        return None


def _hash_password(password: str, salt: str = None) -> str:
    """PBKDF2 hash using only Python's stdlib — no extra package needed."""
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"{salt}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except Exception:
        return False
    return secrets.compare_digest(_hash_password(password, salt), stored)


def _generate_strong_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ---------------------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------------------
defaults = {
    "logged_in": False,
    "phone": "",
    "name": "",
    "messages": [],
    "doc_text": "",
    "doc_name": "",
    "theme": "dark",              # theme toggle state
    "ai_tone": "Professional",    # AI personality/tone
    "current_conversation_id": None,   # active conversation in Supabase
    "pending_image": None,             # bytes of an image waiting to be asked about
    "pending_image_mime": None,
    "_raw_picked_image": None,         # bytes of a freshly picked photo, before editing
    "_marks": [],                      # colour-mark dots placed on the photo being edited
    "_suggested_pw": "",               # last auto-suggested signup password
    "_regenerate_now": False,          # flag to regenerate the last AI reply
    "_regen_index": None,              # index of the assistant message being regenerated
    "_show_admin": False,              # owner-only admin dashboard view
    "_study_prompt": None,             # prompt queued by the Study mode buttons
    "_cap_cache": None,                # {day, phone, used} for the daily message cap
    "auth_open": False,                # False = landing page, True = sign-in card
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val


# ---------------------------------------------------------------------
# THEME CSS (dark / light)
# ---------------------------------------------------------------------
def inject_css(theme: str):
    if theme == "dark":
        bg, fg, sub = "#07070a", "#ececf1", "#a3a3b0"
        card_bg, card_border = "#0f0f14", "#23232c"
        input_bg, input_border = "#0f0f14", "#2c2c36"
        btn_bg, btn_border, btn_hover = "#14141b", "#2c2c36", "#1d1d26"
        sidebar_bg, sidebar_border = "#0a0a0e", "#1c1c24"
        title_color = "#ffffff"
    else:
        bg, fg, sub = "#f7f7f9", "#0c0c10", "#5d5d68"
        card_bg, card_border = "#ffffff", "#e3e3e9"
        input_bg, input_border = "#ffffff", "#d2d2da"
        btn_bg, btn_border, btn_hover = "#ececf0", "#d2d2da", "#e0e0e6"
        sidebar_bg, sidebar_border = "#f0f0f4", "#e3e3e9"
        title_color = "#0c0c10"

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
        /* Minimal icon-style buttons (like/dislike/regenerate) — no box, just a subtle icon */
        div[class*="st-key-up_"] button,
        div[class*="st-key-down_"] button,
        div[class*="st-key-regen_"] button {{
            background: transparent !important;
            border: none !important;
            padding: 0.1rem 0.35rem !important;
            font-weight: 400 !important;
            opacity: 0.6;
            box-shadow: none !important;
        }}
        div[class*="st-key-up_"] button:hover,
        div[class*="st-key-down_"] button:hover,
        div[class*="st-key-regen_"] button:hover {{
            background: rgba(148, 163, 184, 0.15) !important;
            opacity: 1;
            border-radius: 6px;
        }}
        /* Keep the copy/like/dislike/regenerate row horizontal even on narrow mobile screens */
        div[class*="st-key-actions_"] [data-testid="stHorizontalBlock"] {{
            flex-direction: row !important;
            flex-wrap: nowrap !important;
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
            background: linear-gradient(135deg, #c4121f 0%, #7d0e17 100%);
            border: 1px solid rgba(255, 59, 74, 0.45);
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
        .chat-bubble pre {{
            background-color: #0b0f19;
            border: 1px solid #1f2937;
            border-radius: 8px;
            padding: 0.6rem 0.7rem;
            overflow-x: auto;
            margin: 0.4rem 0;
        }}
        .chat-bubble pre code {{
            background: none;
            color: #e2e8f0;
            font-size: 0.8rem;
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
        }}
        .chat-bubble code {{
            background-color: rgba(148, 163, 184, 0.18);
            border-radius: 4px;
            padding: 0.1rem 0.3rem;
            font-size: 0.85em;
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
        }}
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
        /* Attached photo preview chip — hide filename/size text, keep a clean bigger thumbnail */
        [data-testid="stChatInputFile"] p,
        [data-testid="stChatInputFile"] small,
        [data-testid="stChatInputFile"] span:not(:has(svg)) {{
            display: none !important;
        }}
        [data-testid="stChatInputFile"] img {{
            width: 64px !important;
            height: 64px !important;
            object-fit: cover !important;
            border-radius: 10px !important;
        }}
    </style>
    """, unsafe_allow_html=True)


_ORB_SVG = r"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 800"><defs><radialGradient id="g" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="#ff2a3a" stop-opacity=".5"/><stop offset=".55" stop-color="#e11d2e" stop-opacity=".15"/><stop offset="1" stop-color="#e11d2e" stop-opacity="0"/></radialGradient><radialGradient id="o" cx="34%" cy="28%" r="80%"><stop offset="0" stop-color="#4b4b57"/><stop offset=".28" stop-color="#17171d"/><stop offset=".7" stop-color="#050507"/><stop offset="1" stop-color="#000"/></radialGradient><radialGradient id="c" cx="70%" cy="74%" r="55%"><stop offset="0" stop-color="#ff2a3a" stop-opacity=".95"/><stop offset=".45" stop-color="#b3101c" stop-opacity=".5"/><stop offset="1" stop-color="#b3101c" stop-opacity="0"/></radialGradient><linearGradient id="r" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".95"/><stop offset=".5" stop-color="#9a9aa8" stop-opacity=".4"/><stop offset="1" stop-color="#fff" stop-opacity=".85"/></linearGradient><filter id="b" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="14"/></filter></defs><circle cx="400" cy="400" r="392" fill="none" stroke="#e11d2e" stroke-opacity=".4" stroke-width="2"/><circle cx="400" cy="400" r="336" fill="url(#g)"/><g transform="rotate(-24 400 400)" fill="none"><ellipse cx="400" cy="400" rx="318" ry="104" stroke="#e11d2e" stroke-opacity=".4" stroke-width="18" filter="url(#b)"/><ellipse cx="400" cy="400" rx="318" ry="104" stroke="url(#r)" stroke-width="7" stroke-opacity=".55"/></g><circle cx="400" cy="400" r="212" fill="url(#o)"/><circle cx="400" cy="400" r="212" fill="url(#c)"/><ellipse cx="334" cy="316" rx="88" ry="46" fill="#fff" fill-opacity=".24" filter="url(#b)" transform="rotate(-32 334 316)"/><g transform="rotate(-24 400 400)" fill="none"><path d="M82 400 A318 104 0 0 0 718 400" stroke="url(#r)" stroke-width="7"/><circle cx="718" cy="400" r="9" fill="#ff3b4a"/><circle cx="82" cy="400" r="6" fill="#fff" fill-opacity=".8"/></g></svg>"""


def inject_theme_css(theme: str, view: str):
    """The black-and-red 'AI interface' look: fonts, landing hero, sign-in card, responsive rules."""
    t = {"RED": "#e11d2e", "REDHI": "#ff3b4a", "REDRGB": "225,29,46", "FG": "#ececf1", "MUTED": "#a3a3b0",
         "BG": "#07070a", "SURF": "15,15,20", "BORDER": "#26262f", "GLOW": "0.10"}
    if theme != "dark":
        t = {"RED": "#d4141f", "REDHI": "#ec2230", "REDRGB": "212,20,31", "FG": "#0c0c10", "MUTED": "#5d5d68",
             "BG": "#f7f7f9", "SURF": "255,255,255", "BORDER": "#e0e0e7", "GLOW": "0.07"}
    t["MAXW"] = "1240px" if view == "landing" else "880px"
    t["ORB"] = urllib.parse.quote(_ORB_SVG, safe="")
    css = """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;800&family=Inter:wght@400;500;600&display=swap');
    :root { --red: __RED__; --red-hi: __REDHI__; --fg: __FG__; --muted: __MUTED__; --bg: __BG__; --border: __BORDER__; }
    html, body, .stApp { overflow-x: hidden; }
    .stApp {
        font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
        background: radial-gradient(900px 520px at 85% -8%, rgba(__REDRGB__, __GLOW__), transparent 62%), var(--bg) !important;
    }
    /* quiet the Streamlit chrome so it reads as a product, not a script */
    [data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu, footer { display: none !important; }
    [data-testid="stHeader"] { background: transparent !important; }
    [data-testid="stMainBlockContainer"], .block-container {
        max-width: __MAXW__ !important;
        padding: 2.2rem clamp(1rem, 4vw, 3.5rem) 5.5rem !important;
    }
    [data-testid="stMain"], [data-testid="stSidebar"] { position: relative; z-index: 1; }
    div.stButton > button:hover { border-color: var(--red); }
    input:focus, textarea:focus { border-color: var(--red) !important; box-shadow: 0 0 0 1px var(--red) !important; }
    [data-testid="stChatInput"] textarea:focus, [data-testid="stChatInput"] input:focus { border: none !important; box-shadow: none !important; }
    h1, h2, h3, .nix-title { font-family: 'Orbitron', 'Inter', system-ui, sans-serif; }
    .nix-title {
        font-size: clamp(1rem, 3.4vw, 1.35rem) !important; letter-spacing: .08em !important; text-transform: none;
        border-bottom: 1px solid var(--border) !important; padding-bottom: .9rem !important; margin-bottom: 1.1rem !important;
    }
    .chat-bubble.assistant { background: rgba(__SURF__, .92); border-color: var(--border); }
    @media (max-width: 640px) { .chat-bubble { max-width: 90% !important; font-size: .95rem !important; } }

    /* ---------- landing + sign-in ---------- */
    .nix-top { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: .2rem 0 1.2rem; }
    .nix-brand { font-family: 'Orbitron', sans-serif; font-weight: 800; letter-spacing: .24em; font-size: clamp(.8rem, 2.6vw, 1rem); color: var(--fg); display: flex; align-items: center; gap: .65rem; }
    .nix-brand i { width: .55rem; height: .55rem; border-radius: 50%; background: var(--red); box-shadow: 0 0 14px var(--red); display: inline-block; }
    .nix-contact { font-size: .68rem; letter-spacing: .22em; text-transform: uppercase; color: var(--fg) !important; text-decoration: none !important;
        border: 1px solid rgba(__REDRGB__, .6); padding: .6rem 1.15rem; border-radius: 999px; white-space: nowrap; }
    .nix-contact:hover { background: rgba(__REDRGB__, .16); }
    .nix-copy { max-width: min(100%, 40rem); margin-top: clamp(.6rem, 5vh, 3.2rem); }
    .nix-tags { border-left: 2px solid var(--red); padding-left: .8rem; font-size: .6rem; letter-spacing: .3em; line-height: 1.7; color: var(--muted); margin-bottom: clamp(1rem, 3.5vh, 2rem); }
    .nix-tags span { display: block; }
    .nix-h1 { font-family: 'Orbitron', sans-serif !important; font-weight: 800 !important; text-transform: uppercase; line-height: 1.04 !important;
        letter-spacing: .01em !important; margin: 0 !important; padding: 0 !important; color: var(--fg); font-size: clamp(2.3rem, 13vw, 4.5rem) !important; }
    .nix-h1 .ln { display: block; }
    .nix-h1 [data-testid="stHeaderActionElements"] { display: none !important; }
    .nix-h1 .r { color: var(--red); text-shadow: 0 0 34px rgba(__REDRGB__, .45); }
    .nix-copy .nix-sub { font-size: .72rem; letter-spacing: .24em; text-transform: uppercase; color: var(--muted); margin: 1.5rem 0 1.8rem !important; line-height: 1.9; }
    div[class*="st-key-hero_actions"] [data-testid="stHorizontalBlock"] { flex-direction: row !important; flex-wrap: wrap !important; gap: .8rem !important; width: auto !important; }
    div[class*="st-key-hero_actions"] [data-testid="stColumn"] { flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; }
    div[class*="st-key-btn_login"] button, div[class*="st-key-btn_signup"] button, div[class*="st-key-btn_create"] button, div[class*="st-key-btn_do_login"] button { font-family: 'Orbitron', sans-serif !important; font-size: .74rem !important; letter-spacing: .18em !important; text-transform: uppercase;
        font-weight: 700 !important; border-radius: 999px !important; min-height: 3rem; padding: .8rem 2rem !important; transition: all .18s ease; }
    div[class*="st-key-btn_login"] button p, div[class*="st-key-btn_signup"] button p, div[class*="st-key-btn_create"] button p, div[class*="st-key-btn_do_login"] button p { font-family: inherit !important; letter-spacing: inherit; font-weight: inherit; }
    div[class*="st-key-btn_login"] button, div[class*="st-key-btn_create"] button, div[class*="st-key-btn_do_login"] button {
        background: var(--red) !important; border: 1px solid var(--red) !important; color: #fff !important; box-shadow: 0 0 28px rgba(__REDRGB__, .42); }
    div[class*="st-key-btn_login"] button:hover, div[class*="st-key-btn_create"] button:hover, div[class*="st-key-btn_do_login"] button:hover { background: var(--red-hi) !important; border-color: var(--red-hi) !important; }
    div[class*="st-key-btn_signup"] button { background: #fff !important; border: 1px solid #fff !important; color: #0c0c10 !important; }
    div[class*="st-key-btn_signup"] button:hover { background: #e7e7ec !important; }
    div[class*="st-key-btn_create"] button, div[class*="st-key-btn_do_login"] button { width: 100%; }
    div[class*="st-key-actions_"] [data-testid="stColumn"] { min-width: 0 !important; }
    div[class*="st-key-actions_"] button { width: 100% !important; min-height: 2.3rem !important; }
    div[class*="st-key-auth_card"] [data-testid="stHorizontalBlock"] { flex-direction: row !important; flex-wrap: nowrap !important; align-items: flex-end; gap: .6rem !important; }
    div[class*="st-key-auth_card"] [data-testid="stColumn"] { min-width: 0 !important; }
    div[class*="st-key-btn_suggest_pw"] button { min-height: 2.75rem; padding: 0 .9rem; border-radius: 12px; }
    div[class*="st-key-auth_back"] button { font-size: .72rem !important; letter-spacing: .14em; color: var(--muted) !important; }
    div[class*="st-key-auth_card"] { max-width: 30rem; margin: .6rem auto 0; padding: 1.4rem clamp(1rem, 4vw, 1.8rem) 1.1rem;
        border: 1px solid rgba(__REDRGB__, .4); border-radius: 18px; background: rgba(__SURF__, .78);
        backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px); box-shadow: 0 0 70px rgba(__REDRGB__, .12); }
    .nix-card-title { font-family: 'Orbitron', sans-serif; font-weight: 700; letter-spacing: .2em; font-size: .78rem; margin-bottom: .9rem; color: var(--fg); }
    .nix-help { margin-top: auto; padding-top: 2.4rem; display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: .35rem 1rem;
        font-size: .86rem; color: var(--fg); text-align: center; line-height: 1.6; }
    .nix-help .l { font-size: .62rem; letter-spacing: .26em; text-transform: uppercase; color: var(--muted); width: 100%; }
    .nix-help a { color: var(--fg) !important; text-decoration: none !important; border-bottom: 1px solid rgba(__REDRGB__, .85); padding-bottom: 1px; font-weight: 500; }
    div[data-testid="stElementContainer"]:has(.nix-help) { margin-top: auto; }
    [data-testid="stMainBlockContainer"] > div[data-testid="stVerticalBlock"] { min-height: calc(100vh - 7.5rem); }
    __ORBCSS__
    </style>
    """
    orb_css = ""
    if view == "landing":
        orb_css = """
    [data-testid="stAppViewContainer"]::before { content: ""; position: fixed; inset: 0; z-index: 0; pointer-events: none;
        background-image: url("data:image/svg+xml;utf8,__ORB__"); background-repeat: no-repeat;
        background-position: right clamp(0rem, 3vw, 4rem) center; background-size: min(60vw, 84vh, 800px); }
    @media (max-width: 820px) {
        [data-testid="stAppViewContainer"]::before { background-position: 50% 118%; background-size: min(124vw, 600px); opacity: .7; }
    }"""
    css = css.replace("__ORBCSS__", orb_css)
    for k, v in t.items():
        css = css.replace(f"__{k}__", v)
    st.markdown(css, unsafe_allow_html=True)


inject_css(st.session_state.theme)

inject_theme_css(st.session_state.theme, "chat" if st.session_state.logged_in else "landing")

if st.session_state.logged_in and st.session_state.name:
    st.markdown(f"<h1 class='nix-title'>Heyy {_html_lib.escape(st.session_state.name)} 👋🏾</h1>", unsafe_allow_html=True)


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


def _classify_error(e) -> str:
    """Sort an API error into: auth, missing, quota_day, quota_minute, transient, other."""
    t = str(e).lower()
    squashed = t.replace(" ", "").replace("_", "")
    code = getattr(e, "code", None)
    if not isinstance(code, int):
        code = getattr(e, "status_code", None)
    if code in (401, 403) or any(k in t for k in ("api key not valid", "api_key_invalid", "unauthenticated", "permission_denied")):
        return "auth"
    if code == 404 or any(k in t for k in ("not_found", "no longer available", "is not found")):
        return "missing"
    if code == 429 or any(k in t for k in ("resource_exhausted", "quota", "rate limit", "429")):
        if any(k in squashed for k in ("perday", "requestsperday", "daily")):
            return "quota_day"
        return "quota_minute"
    if code in (500, 502, 503, 504) or any(k in t for k in ("503", "overloaded", "unavailable", "deadline", "timeout", "timed out", "connection", "temporarily")):
        return "transient"
    return "other"


def _with_retry(fn, max_attempts=3, base_delay=1.0):
    """Retries only short hiccups (503, timeouts). Quota, missing-model and key errors fail
    straight away, because waiting won't fix them."""
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            if _classify_error(e) != "transient" or attempt == max_attempts - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))  # 1s, 2s


FOUNDER_ANSWER = "Yo 👋 I was built by NIYAR DAS — the mastermind behind NIX AI"
_FOUNDER_PATTERNS = [
    "who created you", "who made you", "who is your founder", "who's your founder",
    "your founder", "who developed you", "who built you", "who owns you",
    "your creator", "who is your creator", "who's your creator",
]

NIYAR_BIO_ANSWER = "Niyar Das — a software developer deep into AI and entrepreneurship, plus a sharp chess player on the side."
_NIYAR_BIO_PATTERNS = [
    "who is niyar das", "who's niyar das", "who is niyar", "who's niyar",
    "about niyar das", "tell me about niyar",
]


def _is_founder_question(text: str) -> bool:
    t = (text or "").lower()
    return any(p in t for p in _FOUNDER_PATTERNS)


def _is_niyar_bio_question(text: str) -> bool:
    t = (text or "").lower()
    return any(p in t for p in _NIYAR_BIO_PATTERNS)


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


def _actions_widget_html(text: str, bg: str) -> str:
    """Tiny iframe widget with copy and read-aloud icons. It runs in an iframe because
    Streamlit's markdown does not run inline JS handlers."""
    payload = json.dumps(text or "").replace("</", "<\\/").replace("<!--", "<\\!--")
    return f"""
    <style>html, body {{ margin: 0; background: {bg}; }}</style>
    <div style="display:flex;gap:2px;justify-content:center;align-items:center;
                font-size:17px;font-family:sans-serif;height:30px;">
      <span id="c" title="Copy" style="cursor:pointer;opacity:.65;user-select:none;padding:7px 9px">📋</span>
      <span id="s" title="Read aloud" style="cursor:pointer;opacity:.65;user-select:none;padding:7px 9px">🔊</span>
    </div>
    <script>
      const T = {payload};
      const c = document.getElementById('c');
      const s = document.getElementById('s');
      c.onclick = async () => {{
        try {{ await navigator.clipboard.writeText(T); }}
        catch (e) {{
          const ta = document.createElement('textarea');
          ta.value = T; document.body.appendChild(ta); ta.select();
          try {{ document.execCommand('copy'); }} catch (e2) {{}}
          ta.remove();
        }}
        c.textContent = '✅';
        setTimeout(() => {{ c.textContent = '📋'; }}, 1000);
      }};
      s.onclick = () => {{
        const synth = window.speechSynthesis;
        if (!synth) return;
        if (synth.speaking) {{ synth.cancel(); s.textContent = '🔊'; return; }}
        const clean = T.replace(/[#*_`>]/g, '');
        const u = new SpeechSynthesisUtterance(clean);
        if (/[\\u0900-\\u097F]/.test(clean)) u.lang = 'hi-IN';
        u.onend = () => {{ s.textContent = '🔊'; }};
        u.onerror = () => {{ s.textContent = '🔊'; }};
        s.textContent = '⏹️';
        synth.speak(u);
      }};
    </script>
    """


def _embed_html(html: str, height: int):
    """Render a small trusted HTML/JS snippet in an iframe.
    Uses st.iframe on current Streamlit; falls back to components.html on older versions."""
    if hasattr(st, "iframe"):
        st.iframe(html.strip(), height=height)
    else:
        components.html(html, height=height)


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


# ---------------------------------------------------------------------
# MODEL LADDER: free quotas are per model, so when one is used up we move to the next
# ---------------------------------------------------------------------
_DEFAULT_MODELS = [MODEL_NAME, "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
_COOLDOWN = {"quota_day": 3600, "quota_minute": 60, "missing": 6 * 3600, "transient": 20}


def _model_ladder():
    """Models to try, in order. Set MODEL_NAMES in Secrets (a list or comma-separated) to change them."""
    try:
        raw = st.secrets["MODEL_NAMES"]
    except Exception:
        raw = None
    if raw:
        names = [x.strip() for x in raw.split(",")] if isinstance(raw, str) else [str(x).strip() for x in list(raw)]
        names = [n for n in names if n]
        if names:
            return names
    return list(_DEFAULT_MODELS)


@st.cache_resource
def _quota_board():
    """Shared by every visitor while the app runs: model -> {"until": timestamp, "why": reason}."""
    return {}


def _bench(model, kind, err_text=""):
    """Rest a model for a while so nobody waits on one we already know is out."""
    seconds = _COOLDOWN.get(kind, 60)
    if kind == "quota_minute":
        m = re.search(r"retrydelay\W+(\d+)", err_text.lower())
        if m:
            seconds = min(max(int(m.group(1)) + 2, 5), 300)
    _quota_board()[model] = {"until": time.time() + seconds, "why": kind}


def _live_models():
    now = time.time()
    board = _quota_board()
    return [m for m in _model_ladder() if board.get(m, {}).get("until", 0) <= now]


class _AllModelsDown(Exception):
    pass


def _ai_down_message():
    now = time.time()
    board = _quota_board()
    ladder = _model_ladder()
    waits = [(board[m]["until"] - now, board[m]["why"]) for m in ladder if m in board and board[m]["until"] > now]
    if not waits:
        return "⚠️ NIX AI is busy right now. Please try again in a minute."
    if len(waits) == len(ladder) and all(why == "missing" for _, why in waits):
        return "⚠️ The AI models aren't available right now. (Owner: check MODEL_NAMES in Secrets.)"
    wait, why = min(waits)
    if wait <= 120:
        if why == "transient":
            return "⚠️ Gemini's servers are busy right now. Please try again in a few seconds."
        return "⚠️ NIX AI is getting a lot of requests right now. Please try again in a minute."
    return "⚠️ NIX AI's free quota for today is used up. It should reset around 1 PM IST, please try again then. 🙏"


def _run_ladder(call):
    """Try each live model in turn. call(model) returns the reply text."""
    for model in _live_models():
        try:
            return call(model)
        except Exception as e:
            kind = _classify_error(e)
            if kind in ("auth", "other"):
                raise  # another model won't fix a bad key or a bad request
            _bench(model, kind, str(e))
    raise _AllModelsDown(_ai_down_message())


def _friendly_error(e, prefix="⚠️ Something went wrong talking to Gemini:"):
    kind = _classify_error(e)
    if kind == "transient":
        return "⚠️ Gemini's servers are busy right now. Please try again in a few seconds."
    if kind == "auth":
        return "⚠️ API key issue — please check the key in Settings/Secrets."
    return f"{prefix} {e}"


def _type_out(text, placeholder):
    if not placeholder:
        return
    for partial in _typewriter(text):
        placeholder.markdown(_bubble_html(partial + "▌", "assistant"), unsafe_allow_html=True)
    placeholder.markdown(_bubble_html(text, "assistant"), unsafe_allow_html=True)


def _call_model(model, full_prompt, contents, stream_placeholder):
    """One model, best API first. Returns the reply text, or raises the API's error."""
    if hasattr(client, "interactions"):
        try:
            if stream_placeholder:
                stream_placeholder.markdown(_loading_bubble_html(), unsafe_allow_html=True)
            result = _with_retry(lambda: client.interactions.create(model=model, input=full_prompt))
            text = result.output_text
            if not text:
                raise ValueError("The model returned an empty reply")
            _type_out(text, stream_placeholder)
            return text
        except Exception as e:
            if _classify_error(e) != "other":
                raise
            # the Interactions API isn't usable here (older SDK or key): use the classic API below
    if hasattr(client.models, "generate_content_stream"):
        try:
            def _run_stream():
                collected = ""
                for chunk in client.models.generate_content_stream(model=model, contents=contents):
                    piece = getattr(chunk, "text", "") or ""
                    collected += piece
                    if stream_placeholder:
                        stream_placeholder.markdown(_bubble_html(collected + "▌", "assistant"), unsafe_allow_html=True)
                return collected
            collected = _with_retry(_run_stream)
            if not collected:
                raise ValueError("The model returned an empty reply")
            if stream_placeholder:
                stream_placeholder.markdown(_bubble_html(collected, "assistant"), unsafe_allow_html=True)
            return collected
        except Exception as e:
            if _classify_error(e) != "other":
                raise
    response = _with_retry(lambda: client.models.generate_content(model=model, contents=contents))
    text = response.text
    if not text:
        raise ValueError("The model returned an empty reply")
    _type_out(text, stream_placeholder)
    return text


# ---------------------------------------------------------------------
# READY-MADE REPLIES: "hi", "thanks" and friends don't need the AI (saves quota)
# ---------------------------------------------------------------------
_GREET_RE = re.compile(r"^(h+i+|he+y+|he+l+o+|yo+|hola|namaste|namaskar|ram ram|sup|gm|good (morning|afternoon|evening))( (there|bro|buddy|nix|nix ai|bhai|dost))?$")
_THANKS_RE = re.compile(r"^(thanks?|thank you|thank u|thanku|thx|ty|shukriya|dhanyavad|dhanyawad)( (a lot|so much|nix|bro|bhai|again))*$")
_BYE_RE = re.compile(r"^(bye+|good ?bye|see you|see ya|ok bye|okay bye|tata|gn|good night|shubh ratri)$")
_ACK_RE = re.compile(r"^(ok+|okay+|okk+|k|kk|alright|cool|nice|great|got it|theek hai|thik hai|acha|accha|hmm+|hm+)$")


def _local_reply(text, history):
    """A canned reply for a bare greeting / thanks / goodbye / 'ok', else None (the AI answers)."""
    if not text or "?" in text:
        return None
    t = re.sub(r"[^a-z0-9\u0900-\u097f ]+", " ", text.lower())
    t = re.sub(r"\s+", " ", t).strip()
    if not t or len(t.split()) > 5:
        return None
    name = (st.session_state.get("name") or "").strip()
    who = f" {name}" if name else ""
    casual = st.session_state.get("ai_tone") == "Casual / Gen-Z"
    if _GREET_RE.match(t):
        return random.choice([f"Yo{who}! 👋 What's up?", f"Heyy{who} 👋 What are we doing today?"] if casual
                             else [f"Hello{who}! 👋 How can I help you today?", f"Hi{who}! What can I help you with?"])
    if _THANKS_RE.match(t):
        return random.choice(["Anytime! 🙌", "You got it 😎 Anything else?"] if casual
                             else ["You're welcome! 😊 Anything else I can help with?", "Happy to help! Let me know if you need anything else."])
    if _BYE_RE.match(t):
        return random.choice(["See you! 👋", "Take care! 👋"])
    if _ACK_RE.match(t):
        last = next((m for m in reversed(history or []) if m.get("role") == "assistant"), None)
        if last and "?" in (last.get("content") or "")[-200:]:
            return None  # the AI just asked something, so "ok" is a real answer
        return "👍 Let me know if you need anything else."
    return None


def _is_local_prompt(text, history):
    return bool(_is_founder_question(text) or _is_niyar_bio_question(text) or _local_reply(text, history))


def ai_available(text="", has_image=False):
    """False (with a notice) only when every model is known to be out and this message needs the AI."""
    if client is None or _live_models():
        return True
    if text and not has_image and _is_local_prompt(text, st.session_state.messages):
        return True
    st.warning(_ai_down_message())
    return False


def ask_ai(prompt, system_context="", stream_placeholder=None):
    """
    Calls Gemini. If the SDK supports streaming (generate_content_stream), uses it
    for real token-by-token output. Otherwise falls back to a typewriter effect
    over the full response so the UI still feels alive.
    Returns the final full text.
    """
    # Founder/creator questions always get this exact answer — no need to call the API
    if _is_founder_question(prompt):
        if stream_placeholder:
            for partial in _typewriter(FOUNDER_ANSWER):
                stream_placeholder.markdown(_bubble_html(partial + "▌", "assistant"), unsafe_allow_html=True)
            stream_placeholder.markdown(_bubble_html(FOUNDER_ANSWER, "assistant"), unsafe_allow_html=True)
        return FOUNDER_ANSWER

    # "Who is Niyar Das?" also gets a fixed answer
    if _is_niyar_bio_question(prompt):
        if stream_placeholder:
            for partial in _typewriter(NIYAR_BIO_ANSWER):
                stream_placeholder.markdown(_bubble_html(partial + "▌", "assistant"), unsafe_allow_html=True)
            stream_placeholder.markdown(_bubble_html(NIYAR_BIO_ANSWER, "assistant"), unsafe_allow_html=True)
        return NIYAR_BIO_ANSWER

    # Greetings / thanks / goodbyes get a ready-made reply, no AI call
    local = _local_reply(prompt, st.session_state.messages[:-1])
    if local:
        _type_out(local, stream_placeholder)
        return local

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

    tone_instructions = {
        "Professional": "Respond in a clear, professional, and concise tone.",
        "Casual / Gen-Z": "Respond in a casual, relaxed, Gen-Z tone — friendly and natural, like texting a friend.",
        "Explain Simply": "Explain things in the simplest possible way, like to a beginner, avoiding jargon.",
    }
    tone = tone_instructions.get(st.session_state.get("ai_tone", "Professional"), tone_instructions["Professional"])

    full_prompt = f"Style instruction: {tone}\n\n"
    if system_context:
        full_prompt += f"Context:\n{system_context}\n\n"
    if transcript:
        full_prompt += f"Conversation so far:\n{transcript}\n"
    full_prompt += f"User: {prompt}"

    history_formatted = [
        {
            "role": "user" if m["role"] == "user" else "model",
            "parts": [{"text": m["content"]}],
        }
        for m in st.session_state.messages[:-1]
    ]
    contents = history_formatted + [{"role": "user", "parts": [{"text": full_prompt}]}]

    try:
        return _run_ladder(lambda model: _call_model(model, full_prompt, contents, stream_placeholder))
    except _AllModelsDown as down:
        err = str(down)
    except Exception as e:
        err = _friendly_error(e)
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

    def _vision_call(model):
        response = _with_retry(lambda: client.models.generate_content(model=model, contents=contents))
        text = response.text
        if not text:
            raise ValueError("The model returned an empty reply")
        _type_out(text, stream_placeholder)
        return text

    try:
        return _run_ladder(_vision_call)
    except _AllModelsDown as down:
        err = str(down)
    except Exception as e:
        err = _friendly_error(e, prefix="⚠️ Couldn't analyze the image:")
    if stream_placeholder:
        stream_placeholder.markdown(_bubble_html(err, "assistant"), unsafe_allow_html=True)
    return err


# ---------------------------------------------------------------------
# LOGIN PAGE
# ---------------------------------------------------------------------
def _suggest_password():
    """on_click callback: runs before the password box is built, so it may set its value."""
    pw = _generate_strong_password()
    st.session_state.su_password = pw
    st.session_state._suggested_pw = pw


def _auth_form():
    mode = st.radio("Mode", ["Log in", "Sign up"], horizontal=True, label_visibility="collapsed", key="auth_mode")

    if mode == "Sign up":
        name = st.text_input("Your Name", placeholder="e.g. Rohan", key="su_name")
        phone = st.text_input("Phone Number", max_chars=10, placeholder="9876543210", key="su_phone")

        if "su_password" not in st.session_state:
            st.session_state.su_password = ""

        pw_col, btn_col = st.columns([4, 1])
        with pw_col:
            password = st.text_input("Password", type="password", key="su_password")
        with btn_col:
            st.markdown("<div style='height:1.6rem'></div>", unsafe_allow_html=True)
            st.button("🔑", help="Suggest a strong password", key="btn_suggest_pw", on_click=_suggest_password)

        if st.session_state.get("_suggested_pw") and st.session_state.su_password == st.session_state._suggested_pw:
            st.caption(f"Suggested password: `{st.session_state._suggested_pw}` — save it somewhere safe. You can edit it above.")

        if st.button("Create account", key="btn_create"):
            if not name.strip():
                st.error("Please enter your name.")
            elif not (phone.isdigit() and len(phone) == 10):
                st.error("Please enter a valid 10-digit number.")
            elif len(password) < 4:
                st.error("Password should be at least 4 characters.")
            elif not db_available():
                st.error("Sign up needs Supabase set up (SUPABASE_URL / SUPABASE_KEY in Secrets).")
            elif db_get_user(phone):
                st.error("This phone number is already registered. Please log in instead.")
            else:
                db_create_user(phone, name.strip(), _hash_password(password))
                st.session_state.name = name.strip()
                st.session_state.phone = phone
                st.session_state.logged_in = True
                st.rerun()

    else:  # Log in
        phone = st.text_input("Phone Number", max_chars=10, placeholder="9876543210", key="li_phone")
        password = st.text_input("Password", type="password", key="li_password")
        if st.button("Log in", key="btn_do_login"):
            if not db_available():
                st.error("Login needs Supabase set up (SUPABASE_URL / SUPABASE_KEY in Secrets).")
            else:
                user = db_get_user(phone)
                if not user or not _verify_password(password, user.get("password_hash", "")):
                    st.error("Incorrect phone number or password.")
                else:
                    st.session_state.name = user.get("name", "")
                    st.session_state.phone = phone
                    st.session_state.logged_in = True
                    st.rerun()


_TOPBAR_HTML = (
    '<div class="nix-top"><div class="nix-brand"><i></i>NIX AI</div>'
    '<a class="nix-contact" href="mailto:niyardaxx@gmail.com">Contact</a></div>'
)


def _help_html() -> str:
    wa_link = "https://wa.me/918822166691?text=" + urllib.parse.quote("Hey Niyar, I need help with NIX AI 🙏")
    return (
        '<div class="nix-help"><span class="l">For any kind of help, contact</span>'
        '<a href="mailto:niyardaxx@gmail.com">niyardaxx@gmail.com</a><span>or</span>'
        f'<a href="{wa_link}" target="_blank" rel="noopener">WhatsApp +91 88221 66691</a></div>'
    )


def _open_auth(mode):
    st.session_state.auth_open = True
    st.session_state.auth_mode = mode
    st.rerun()


def login_page():
    if not st.session_state.get("auth_open"):
        st.markdown(
            _TOPBAR_HTML
            + '<div class="nix-copy"><div class="nix-tags"><span>ASK</span><span>LEARN</span><span>CREATE</span><span>EXPLORE</span></div>'
            '<h1 class="nix-h1"><span class="ln">NIX AI</span><span class="ln">THE NEXT</span><span class="ln r">GEN AI</span></h1>'
            '<p class="nix-sub">Ask anything. Learn faster. Create more.</p></div>',
            unsafe_allow_html=True,
        )
        with st.container(key="hero_actions"):
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Log in  →", key="btn_login"):
                    _open_auth("Log in")
            with c2:
                if st.button("Sign up", key="btn_signup"):
                    _open_auth("Sign up")
    else:
        st.markdown(_TOPBAR_HTML, unsafe_allow_html=True)
        with st.container(key="auth_card"):
            st.markdown('<div class="nix-card-title">ACCESS NIX AI</div>', unsafe_allow_html=True)
            _auth_form()
            if st.button("← Back", key="auth_back", type="tertiary"):
                st.session_state.auth_open = False
                st.rerun()
    st.markdown(_help_html(), unsafe_allow_html=True)


# ---------------------------------------------------------------------
# MAIN APP
# ---------------------------------------------------------------------
def render_admin_dashboard():
    st.subheader("📊 Admin dashboard")
    st.caption("Totals only. Chat content is never shown here.")
    if not db_available():
        st.warning("Supabase isn't connected, so there's nothing to show yet.")
        return
    stats = db_admin_stats()
    c1, c2, c3 = st.columns(3)
    c1.metric("Users", stats["users"] if stats["users"] is not None else "—")
    c2.metric("Chats", stats["conversations"] if stats["conversations"] is not None else "—")
    c3.metric("Messages", stats["messages"] if stats["messages"] is not None else "—")
    st.markdown("#### AI models")
    now = time.time()
    board = _quota_board()
    model_rows = []
    for i, m in enumerate(_model_ladder(), 1):
        b = board.get(m)
        if b and b["until"] > now:
            label = {"quota_day": "daily quota used up", "quota_minute": "rate-limited", "missing": "not found", "transient": "busy"}.get(b["why"], b["why"])
            status = f"{label} (retry in ~{max(1, int((b['until'] - now) / 60))} min)"
        else:
            status = "ready"
        model_rows.append({"Order": i, "Model": m, "Status": status})
    st.dataframe(model_rows, hide_index=True, use_container_width=True)
    if st.button("Re-check models now", key="recheck_models"):
        board.clear()
        st.rerun()
    st.markdown("#### Recent signups")
    rows = []
    for u in stats["recent_users"]:
        phone = str(u.get("phone") or "")
        rows.append({
            "Name": u.get("name") or "—",
            "Phone": ("•••••• " + phone[-4:]) if len(phone) >= 4 else "—",
            "Joined": str(u.get("created_at") or "")[:10],
        })
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.caption("No signups yet.")


def main_app():
    # The sign-up / log-in password boxes are gone once you're in, so drop whatever was typed.
    # (Doing this here is safe; clearing them inside login_page after the widget exists is not.)
    for _k in ("su_password", "li_password", "_suggested_pw"):
        st.session_state.pop(_k, None)

    with st.sidebar:
        # --- Chat history: new chat + past conversations ---
        st.subheader("Chats")
        if st.button("➕ New Chat"):
            st.session_state.messages = []
            st.session_state.current_conversation_id = None
            st.rerun()

        _cap = daily_cap_for(st.session_state.phone)
        if _cap is not None and db_available():
            _used = messages_used_today(st.session_state.phone)
            st.caption(f"💬 {max(_cap - _used, 0)} of {_cap} messages left today")

        if db_available():
            convos = db_list_conversations(st.session_state.phone)
            if not convos:
                st.caption("No past chats yet.")
            for c in convos:
                label = c.get("title") or "Untitled chat"
                is_active = c["id"] == st.session_state.current_conversation_id
                col_t, col_r, col_d = st.columns([5, 1, 1])
                with col_t:
                    if st.button(("• " if is_active else "") + label, key=f"conv_{c['id']}"):
                        st.session_state.current_conversation_id = c["id"]
                        st.session_state.messages = db_load_messages(c["id"])
                        st.rerun()
                with col_r:
                    if st.button("✏️", key=f"ren_{c['id']}"):
                        st.session_state[f"_renaming_{c['id']}"] = not st.session_state.get(f"_renaming_{c['id']}", False)
                with col_d:
                    if st.button("🗑️", key=f"del_{c['id']}"):
                        db_delete_conversation(c["id"])
                        if st.session_state.current_conversation_id == c["id"]:
                            st.session_state.current_conversation_id = None
                            st.session_state.messages = []
                        st.rerun()
                if st.session_state.get(f"_renaming_{c['id']}"):
                    new_name = st.text_input("New name", value=label, key=f"newname_{c['id']}", label_visibility="collapsed")
                    if st.button("Save name", key=f"savename_{c['id']}"):
                        db_rename_conversation(c["id"], new_name.strip() or label)
                        st.session_state[f"_renaming_{c['id']}"] = False
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

        tone_options = ["Professional", "Casual / Gen-Z", "Explain Simply"]
        tone_choice = st.selectbox(
            "AI tone",
            tone_options,
            index=tone_options.index(st.session_state.get("ai_tone", "Professional")),
        )
        if tone_choice != st.session_state.ai_tone:
            st.session_state.ai_tone = tone_choice

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
                st.caption("Study mode")
                if st.button("📝 Make a quiz", key="study_quiz", use_container_width=True):
                    st.session_state._study_prompt = (
                        "Make a 5-question multiple-choice quiz from the document. "
                        "Give options A to D for each question, then an answer key with a one-line explanation."
                    )
                if st.button("🃏 Make flashcards", key="study_cards", use_container_width=True):
                    st.session_state._study_prompt = (
                        "Make 8 flashcards from the document. Format each as **Q:** question and **A:** answer."
                    )
                if st.button("📒 Short notes", key="study_notes", use_container_width=True):
                    st.session_state._study_prompt = (
                        "Write short, well-organised study notes from the document: key points as bullets under clear headings."
                    )
            else:
                st.error("Failed to parse file.")

        if st.session_state.phone in ADMIN_PHONES:
            st.markdown("---")
            admin_label = "← Back to chat" if st.session_state.get("_show_admin") else "📊 Admin dashboard"
            if st.button(admin_label, key="admin_toggle"):
                st.session_state._show_admin = not st.session_state.get("_show_admin", False)
                st.rerun()

        st.markdown("---")
        if st.button("Terminate Session"):
            for k, v in defaults.items():
                st.session_state[k] = v
            st.rerun()

    if st.session_state.phone in ADMIN_PHONES and st.session_state.get("_show_admin"):
        render_admin_dashboard()
        return

    # --- Handle a pending "regenerate" request from a previous rerun ---
    if st.session_state.get("_regen_index") is not None:
        idx = st.session_state._regen_index
        st.session_state._regen_index = None
        if not (within_daily_cap() and ai_available()):
            idx = -1  # at the limit, or the AI is out: keep the existing reply
        if 0 <= idx < len(st.session_state.messages) and st.session_state.messages[idx]["role"] == "assistant":
            prev_user_msg = None
            for j in range(idx - 1, -1, -1):
                if st.session_state.messages[j]["role"] == "user":
                    prev_user_msg = st.session_state.messages[j]
                    break
            if prev_user_msg is not None:
                with st.spinner("Regenerating..."):
                    img_uri = prev_user_msg.get("image_data_uri")
                    if img_uri:
                        try:
                            header, b64data = img_uri.split(",", 1)
                            mime = header.split(";")[0].replace("data:", "")
                            img_bytes = base64.b64decode(b64data)
                            new_reply = ask_ai_vision(
                                prev_user_msg["content"] or "Describe this image and answer any question in it.",
                                img_bytes, mime,
                            )
                        except Exception:
                            new_reply = ask_ai(prev_user_msg["content"])
                    else:
                        new_reply = ask_ai(prev_user_msg["content"])
                st.session_state.messages[idx]["content"] = new_reply
                st.session_state.messages[idx]["reaction"] = None

    # Render chat history as bubbles: user on the left, assistant on the right, no avatars/icons
    for i, msg in enumerate(st.session_state.messages):
        st.markdown(
            _bubble_html(msg["content"], msg["role"], msg.get("image_data_uri")),
            unsafe_allow_html=True,
        )
        if msg["role"] == "assistant":
            st.markdown(
                "<div style='text-align:right;font-size:0.68rem;opacity:0.45;"
                "margin-top:-4px;margin-bottom:2px;'>NIX is AI and can make mistakes</div>",
                unsafe_allow_html=True,
            )
            with st.container(key=f"actions_{i}"):
                _rspacer, rcol_tools, rcol_up, rcol_down, rcol_regen = st.columns([3, 2, 1, 1, 1])
                reacted = msg.get("reaction")
                with rcol_tools:
                    page_bg = "#07070a" if st.session_state.theme == "dark" else "#f7f7f9"
                    _embed_html(_actions_widget_html(msg["content"], page_bg), height=32)
                with rcol_up:
                    if st.button("👍" if reacted != "up" else "✅", key=f"up_{i}", type="tertiary"):
                        st.session_state.messages[i]["reaction"] = "up"
                        st.rerun()
                with rcol_down:
                    if st.button("👎" if reacted != "down" else "✅", key=f"down_{i}", type="tertiary"):
                        st.session_state.messages[i]["reaction"] = "down"
                        st.rerun()
                with rcol_regen:
                    if st.button("🔄", key=f"regen_{i}", help="Regenerate this reply", type="tertiary"):
                        st.session_state._regen_index = i
                        st.rerun()

    # Quick-start suggestions — only shown on a fresh, empty chat
    quick_prompt = None
    if not st.session_state.messages:
        st.caption("Try asking:")
        suggestions = [
            "Summarize this for me",
            "Explain like I'm 5",
            "Write a short email",
            "Give me 3 startup ideas",
        ]
        qcols = st.columns(2)
        for i, s in enumerate(suggestions):
            with qcols[i % 2]:
                if st.button(s, key=f"quick_{i}", use_container_width=True):
                    quick_prompt = s

    _cap = daily_cap_for(st.session_state.phone)
    if _cap is not None and db_available():
        _left = _cap - messages_used_today(st.session_state.phone)
        if 0 < _left <= 5:
            st.caption(f"⚠️ {_left} message{'s' if _left != 1 else ''} left today")

    # Message box with a built-in attach icon — tapping it on mobile opens the
    # phone's own native Camera / Photo Library picker, just like a normal chat app.
    user_input = st.chat_input(
        "Type a message or query...",
        accept_file=True,
        file_type=["jpg", "jpeg", "png"],
    )

    effective_text = None
    effective_files = []
    if user_input:
        effective_text = (user_input.text or "").strip()
        effective_files = user_input.files or []
    elif quick_prompt:
        effective_text = quick_prompt
    elif st.session_state.get("_study_prompt"):
        effective_text = st.session_state._study_prompt
        st.session_state._study_prompt = None

    if (effective_text or effective_files) and not (
        within_daily_cap() and ai_available(effective_text or "", bool(effective_files))
    ):
        effective_text, effective_files = None, []

    if effective_text or effective_files:
        text = effective_text or ""
        files = effective_files

        # Create a conversation in Supabase on the first message of a new chat
        if st.session_state.current_conversation_id is None and db_available():
            title = (text or "Photo question")[:40]
            st.session_state.current_conversation_id = db_create_conversation(
                st.session_state.phone, st.session_state.name, title
            )

        display_text = text  # may be empty if the person only sent a photo
        image_data_uri = None
        pending_bytes = None
        pending_mime = None
        if files:
            image_file = files[0]
            pending_bytes = image_file.getvalue()
            pending_mime = image_file.type or "image/jpeg"
            image_data_uri = f"data:{pending_mime};base64,{base64.b64encode(pending_bytes).decode('utf-8')}"

        st.session_state.messages.append(
            {"role": "user", "content": display_text, "image_data_uri": image_data_uri}
        )
        st.markdown(_bubble_html(display_text, "user", image_data_uri), unsafe_allow_html=True)
        # Photos aren't stored in the database yet — only the text is saved for history
        db_save_message(st.session_state.current_conversation_id, "user", display_text or "[Photo]")
        _bump_cap_cache()

        placeholder = st.empty()
        placeholder.markdown(_loading_bubble_html(), unsafe_allow_html=True)

        if pending_bytes:
            reply = ask_ai_vision(
                text or "Describe this image and answer any question in it.",
                pending_bytes,
                pending_mime,
                stream_placeholder=placeholder,
            )
        else:
            context = ""
            if st.session_state.doc_text:
                context = f"Reference Document:\n{st.session_state.doc_text[:8000]}"
            reply = ask_ai(text, system_context=context, stream_placeholder=placeholder)

        st.session_state.messages.append({"role": "assistant", "content": reply})
        db_save_message(st.session_state.current_conversation_id, "assistant", reply)
        st.rerun()


# ---------------------------------------------------------------------
# ROUTING
# ---------------------------------------------------------------------
if not st.session_state.logged_in:
    login_page()
else:
    main_app()
