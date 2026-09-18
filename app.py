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

try:
    from supabase import create_client
except ImportError:
    create_client = None
