"""
NIX AI — Professional Gen-Z Minimalist Assistant (Final Working Version)
----------------------------------------------------------------------
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
# Key ab code me nahi, Streamlit secrets me rakhi hai (safe hai public repo ke liye).
# Local pe: .streamlit/secrets.toml file me daalo.
# Streamlit Cloud pe: app dashboard > Settings > Secrets me daalo.
try:
    API_KEY = st.secrets["API_KEY"]
except Exception:
    API_KEY = ""
MODEL_NAME = "gemini-3.8-flash"
OTP_VALID_SECONDS = 300  # 5 min

st.set_page_config(page_title="NIX AI", page_icon="⚡", layout="centered")

# Configure Gemini client with new SDK (works with AQ. and AIzaSy keys both)
client = None
if genai and API_KEY and API_KEY != "APNI_ASLI_KEY_YAHAN_PASTE_KAR_DENA":
    try:
        client = genai.Client(api_key=API_KEY)
    except Exception:
        client = None


# ---------------------------------------------------------------------
# PROFESSIONAL GEN-Z MINIMALIST CSS
# ---------------------------------------------------------------------
st.markdown("""
<style>
    .stApp {
        background-color: #0b0f19;
        color: #e2e8f0;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    }
    h1, h2, h3 { 
        font-weight: 700 !important; 
        letter-spacing: -0.025em;
    }
    .nix-title {
        text-align: center;
        font-size: 2.5rem;
        color: #ffffff;
        margin-bottom: 0;
        font-weight: 800;
    }
    .nix-sub {
        text-align: center;
        color: #94a3b8;
        font-size: 0.95rem;
        margin-top: 4px;
        margin-bottom: 2rem;
        letter-spacing: 0.05em;
    }
    div.stButton > button {
        background: #1e293b;
        color: #f8fafc;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 0.5rem 1.2rem;
        font-weight: 600;
        transition: all 0.2s ease;
    }
    div.stButton > button:hover {
        background: #334155;
        border-color: #475569;
        color: #ffffff;
    }
    section[data-testid="stSidebar"] {
        background-color: #0f172a;
        border-right: 1px solid #1e293b;
    }
    .stChatMessage { 
        background-color: #111827;
        border: 1px solid #1f2937;
        border-radius: 12px;
        padding: 1rem;
    }
    input, textarea {
        background-color: #111827 !important;
        color: #f8fafc !important;
        border-color: #374151 !important;
        border-radius: 8px !important;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("<h1 class='nix-title'>NIX AI</h1>", unsafe_allow_html=True)
st.markdown("<p class='nix-sub'>MINIMAL INTELLIGENCE // SECURE & FAST</p>", unsafe_allow_html=True)


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
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val


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


def ask_ai(prompt, system_context=""):
    if client is None:
        return "⚠️ Please update `API_KEY` in the code with a valid Gemini key from Google AI Studio (starts with `AQ.` or `AIzaSy`)!"

    try:
        # Build conversation history in the format the new SDK expects
        history_formatted = [
            {
                "role": "user" if m["role"] == "user" else "model",
                "parts": [{"text": m["content"]}],
            }
            for m in st.session_state.messages[:-1]
        ]

        full_prompt = f"Context:\n{system_context}\n\nQuery: {prompt}" if system_context else prompt
        contents = history_formatted + [{"role": "user", "parts": [{"text": full_prompt}]}]

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=contents,
        )
        return response.text
    except Exception as e:
        return f"⚠️ Error communicating with Gemini: {e}"


# ---------------------------------------------------------------------
# LOGIN PAGE
# ---------------------------------------------------------------------
def login_page():
    st.subheader("Authentication")
    st.markdown("<p style='color: #64748b; font-size: 0.85rem;'>Enter your mobile number to initialize session.</p>", unsafe_allow_html=True)

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
                        summary = ask_ai(
                            "Provide a clean, concise summary of this document in bullet points:",
                            system_context=text[:12000]
                        )
                    st.markdown("### Summary")
                    st.write(summary)
            else:
                st.error("Failed to parse file.")

        st.markdown("---")
        if st.button("Terminate Session"):
            for k, v in defaults.items():
                st.session_state[k] = v
            st.rerun()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_input = st.chat_input("Type a message or query...")
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Processing..."):
                context = ""
                if st.session_state.doc_text:
                    context = f"Reference Document:\n{st.session_state.doc_text[:8000]}"

                reply = ask_ai(user_input, system_context=context)
                st.markdown(reply)
        st.session_state.messages.append({"role": "assistant", "content": reply})


# ---------------------------------------------------------------------
# ROUTING
# ---------------------------------------------------------------------
if not st.session_state.logged_in:
    login_page()
else:
    main_app()