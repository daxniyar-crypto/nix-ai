import streamlit as st
from google import genai
from google.genai import types
import random

# Page Config
st.set_page_config(
    page_title="Nix AI | Secure Access",
    page_icon="🔒",
    layout="centered"
)

# Initialize Session State variables
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "mobile_number" not in st.session_state:
    st.session_state.mobile_number = ""
if "otp_sent" not in st.session_state:
    st.session_state.otp_sent = False
if "generated_otp" not in st.session_state:
    st.session_state.generated_otp = ""
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- SECURITY GATEWAY (LOGIN) ---
if not st.session_state.logged_in:
    st.markdown("<h2 style='text-align: center;'>🔒 Nix AI Security</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>Please verify your mobile number to access the intelligent workspace.</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        mobile = st.text_input("Enter Mobile Number", placeholder="e.g., 9876543210")
        
        if not st.session_state.otp_sent:
            if st.button("Send OTP", use_container_width=True):
                if len(mobile) == 10 and mobile.isdigit():
                    st.session_state.mobile_number = mobile
                    st.session_state.generated_otp = str(random.randint(1000, 9999))
                    st.session_state.otp_sent = True
                    st.rerun()
                else:
                    st.error("Please enter a valid 10-digit mobile number.")
        else:
            st.info(f"Simulated OTP sent to +91 {st.session_state.mobile_number}")
            st.warning(f"🔑 Your OTP is: **{st.session_state.generated_otp}**")
            
            entered_otp = st.text_input("Enter 4-digit OTP", type="password", max_chars=4)
            
            if st.button("Verify & Login", use_container_width=True):
                if entered_otp == st.session_state.generated_otp:
                    st.session_state.logged_in = True
                    st.success("Access Granted! Loading Nix AI...")
                    st.rerun()
                else:
                    st.error("Invalid OTP. Please try again.")
                    
    st.stop()

# --- MAIN CHAT APPLICATION ---
with st.sidebar:
    st.markdown("### System Status")
    st.success("🟢 Nix Core: Online")
    st.info(f"👤 User: +91 {st.session_state.mobile_number}")
    
    st.markdown("---")
    # Direct Sidebar API Key input (No secrets file needed!)
    user_api_key = st.text_input("Gemini API Key", type="password", placeholder="Paste your API key here")
    
    st.markdown("---")
    if st.button("Logout", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.otp_sent = False
        st.session_state.messages = []
        st.rerun()
        
    if st.button("Clear Conversation", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

st.title("Nix AI")
st.caption("Minimalist Professional Intelligence Workspace")

# Check if user entered the API key in the sidebar
if not user_api_key:
    st.warning("⚠️ Please paste your Gemini API key in the sidebar box on the left to start chatting.")
    st.stop()

try:
    client = genai.Client(api_key=user_api_key)
    model_name = "gemini-2.5-flash"
except Exception as e:
    st.error(f"Failed to initialize client: {e}")
    st.stop()

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat input
if user_prompt := st.chat_input("Ask Nix anything..."):
    st.session_state.messages.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"):
        st.markdown(user_prompt)

    with st.chat_message("assistant"):
        with st.spinner("Nix processing..."):
            try:
                chat_history = [
                    types.Content(
                        role="user" if m["role"] == "user" else "model",
                        parts=[types.Part.from_text(text=m["content"])]
                    )
                    for m in st.session_state.messages[:-1]
                ]
                
                chat_session = client.chats.create(model=model_name, history=chat_history)
                response = chat_session.send_message(user_prompt)
                
                ai_reply = response.text
                st.markdown(ai_reply)
                st.session_state.messages.append({"role": "assistant", "content": ai_reply})
                
            except Exception as e:
                st.error("An error occurred while processing your request. Please check if your API key is correct.")