import random
import streamlit as st
from google import genai
from google.genai import errors

# Page configuration
st.set_page_config(
    page_title="Nix AI - Professional Workspace", page_icon="🤖", layout="centered"
)

# --- BACKEND SECRET CONFIGURATION ---
# API key pre-configured for seamless user experience
MASTER_GEMINI_API_KEY = "AQ.Ab8RN6JvhpYd6Jt4nSeokJ_F-SWXAORpTUrCD239CGC43lPeTA"

# Initialize session state variables
if "logged_in" not in st.session_state:
  st.session_state.logged_in = False
if "otp_sent" not in st.session_state:
  st.session_state.otp_sent = False
if "generated_otp" not in st.session_state:
  st.session_state.generated_otp = ""
if "mobile_number" not in st.session_state:
  st.session_state.mobile_number = ""
if "messages" not in st.session_state:
  st.session_state.messages = []


# --- AUTOMATIC GEMINI AI GENERATOR FUNCTION ---
def get_gemini_response(prompt, file_info):
  file_tag = f" [Attached File: {file_info.name}]" if file_info else ""

  if not prompt.strip():
    return "Please enter a valid message."

  try:
    # Initialize Google GenAI client using the hidden backend key
    client = genai.Client(api_key=MASTER_GEMINI_API_KEY)

    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
    )
    return f"🤖 **Nix AI{file_tag}**\n\n{response.text}"

  except errors.APIError as e:
    return f"❌ **API Error:** {e.message}"
  except Exception as e:
    return f"❌ **Error:** {str(e)}"


# --- LOGIN / AUTHENTICATION SCREEN ---
if not st.session_state.logged_in:
  st.title("🔐 Nix AI - Login")
  st.caption("Enter your mobile number to sign in instantly.")

  mobile_input = st.text_input(
      "Mobile Number", placeholder="Enter 10-digit number"
  )

  if not st.session_state.otp_sent:
    if st.button("Send / Generate OTP", use_container_width=True):
      if mobile_input and len(mobile_input) >= 10:
        st.session_state.mobile_number = mobile_input
        st.session_state.generated_otp = str(random.randint(1000, 9999))
        st.session_state.otp_sent = True
        st.rerun()
      else:
        st.error("Please enter a valid 10-digit mobile number.")
  else:
    st.info(
        f"📱 SMS Simulation: OTP sent to +91 {st.session_state.mobile_number}\n\n"
        f"🔑 Your Auto-Generated OTP is: **{st.session_state.generated_otp}**"
    )

    entered_otp = st.text_input(
        "Enter OTP", type="password", placeholder="Enter 4-digit OTP"
    )

    col1, col2 = st.columns(2)
    with col1:
      if st.button("Verify & Login", use_container_width=True):
        if entered_otp == st.session_state.generated_otp:
          st.session_state.logged_in = True
          st.success("Access Granted! Launching Nix AI...")
          st.rerun()
        else:
          st.error("Invalid OTP. Please try again.")
    with col2:
      if st.button("Resend OTP", use_container_width=True):
        st.session_state.generated_otp = str(random.randint(1000, 9999))
        st.success("New OTP generated!")
        st.rerun()

# --- MAIN CHAT APPLICATION (After Login) ---
else:
  with st.sidebar:
    st.markdown("### ⚙️ Workspace Control")
    st.success("🟢 Nix System: Online")
    st.info(f"👤 User: +91 {st.session_state.mobile_number}")

    st.markdown("---")

    st.markdown("### 📁 File / Photo Drop")
    uploaded_file = st.file_uploader(
        "Drop your image or file here",
        type=["png", "jpg", "jpeg", "pdf", "txt"],
    )

    if uploaded_file is not None:
      st.success(f"File uploaded: {uploaded_file.name}")

    st.markdown("---")

    if st.button("Logout", use_container_width=True):
      st.session_state.logged_in = False
      st.session_state.otp_sent = False
      st.session_state.generated_otp = ""
      st.session_state.messages = []
      st.rerun()

    if st.button("Clear Conversation", use_container_width=True):
      st.session_state.messages = []
      st.rerun()

  st.title("🤖 Nix AI Workspace")
  st.caption("Powered by Advanced Intelligence")

  # Display chat history
  for message in st.session_state.messages:
    with st.chat_message(message["role"]):
      st.markdown(message["content"])
      if "image" in message and message["image"] is not None:
        st.image(
            message["image"],
            caption="Uploaded File/Image",
            use_column_width=True,
        )

  # Chat input
  if prompt := st.chat_input("Ask Nix anything or discuss your uploaded file..."):
    current_file = uploaded_file if uploaded_file else None

    # Append user message
    st.session_state.messages.append({
        "role": "user",
        "content": prompt,
        "image": current_file,
    })

    with st.chat_message("user"):
      st.markdown(prompt)
      if current_file:
        st.image(
            current_file, caption="Uploaded File/Image", use_column_width=True
        )

    # Generate response automatically using the backend key
    with st.spinner("Nix is thinking..."):
      bot_response = get_gemini_response(prompt, current_file)

    # Append assistant response
    st.session_state.messages.append(
        {"role": "assistant", "content": bot_response}
    )
    with st.chat_message("assistant"):
      st.markdown(bot_response)