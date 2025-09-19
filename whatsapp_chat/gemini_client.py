import time
from django.conf import settings
import google.generativeai as genai

# Configure once from settings
genai.configure(api_key=getattr(settings, "GEMINI_API_KEY", None))

MODEL_NAME = getattr(settings, "GEMINI_MODEL", "gemini-1.5-flash")
TEMPERATURE = float(getattr(settings, "GEMINI_TEMPERATURE", 0.2))
MAX_TOKENS = int(getattr(settings, "GEMINI_MAX_TOKENS", 512))

SYSTEM_INSTRUCTIONS = """
You are a Atom.Ai(a WhatsApp assistant). Reply with a SHORT, precise answer.
Prefer bullet points when listing. Avoid long preambles.
"""

def ask_gemini(user_text: str):
    text_in = (user_text or "").strip() or "Hello"
    model = genai.GenerativeModel(MODEL_NAME, system_instruction=SYSTEM_INSTRUCTIONS)

    start = time.monotonic()
    resp = model.generate_content(
        text_in,
        generation_config={
            "temperature": TEMPERATURE,
            "top_p": 0.9,
            "top_k": 32,
            "max_output_tokens": MAX_TOKENS,
        },
    )
    latency_ms = int((time.monotonic() - start) * 1000)
    out = (resp.text or "Sorry, I couldn't generate a response.").strip()
    return out, latency_ms
