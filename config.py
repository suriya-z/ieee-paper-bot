import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
APIMART_API_KEY = os.getenv("APIMART_API_KEY")
AI_MODEL = os.getenv("AI_MODEL", "gemini-3-pro-preview")
APIMART_BASE_URL = os.getenv("APIMART_BASE_URL", "https://api.apimart.ai/v1")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in .env")
if not APIMART_API_KEY:
    raise ValueError("APIMART_API_KEY is not set in .env")
