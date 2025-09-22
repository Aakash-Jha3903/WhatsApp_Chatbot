# whatsapp_chat/openai_client.py
import time
from django.conf import settings
from openai import OpenAI

# Read from Django settings with sane defaults
OPENAI_API_KEY = getattr(settings, "OPENAI_API_KEY", None)
MODEL_NAME = getattr(settings, "OPENAI_MODEL", "gpt-4o-mini")  # pick any available chat model
TEMPERATURE = float(getattr(settings, "OPENAI_TEMPERATURE", 0.2))
MAX_TOKENS = int(getattr(settings, "OPENAI_MAX_TOKENS", 512))

SYSTEM_INSTRUCTIONS = """
You are Atom.Ai (a WhatsApp assistant). Reply with a SHORT, precise answer.
Prefer bullet points when listing. Avoid long preambles.
"""

# Single client reused per process
_client = OpenAI(api_key=OPENAI_API_KEY)

def ask_openai(user_text: str):
    """
    Returns (reply_text, latency_ms)
    """
    text_in = (user_text or "").strip() or "Hello"

    start = time.monotonic()
    resp = _client.chat.completions.create(
        model=MODEL_NAME,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": SYSTEM_INSTRUCTIONS.strip()},
            {"role": "user",   "content": text_in},
        ],
    )
    latency_ms = int((time.monotonic() - start) * 1000)

    # Be defensive if the array is empty
    reply = ""
    if resp.choices and resp.choices[0].message and resp.choices[0].message.content:
        reply = resp.choices[0].message.content.strip()

    reply = reply or "Sorry, I couldn't generate a response."
    return reply, latency_ms
