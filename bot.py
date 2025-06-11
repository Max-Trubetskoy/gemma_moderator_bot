import os
import logging
import json
from io import BytesIO
from fastapi import FastAPI, Request, Response, Header
from typing import Optional
from telegram import Update, Bot
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from google.genai.types import HarmCategory, HarmBlockThreshold, Part
from google.genai import types, Client
import asyncio

# --- Configuration and Initialization ---
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
WEBHOOK_SECRET_TOKEN = os.environ.get('WEBHOOK_SECRET_TOKEN')

if not all([TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, WEBHOOK_SECRET_TOKEN]):
    raise ValueError("Missing required environment variables")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Gemini Model Configuration ---
MODERATION_PROMPT = """
You are an AI content moderator for a Telegram chat group. Your task is to classify incoming messages
(text and images) into one of the following categories: NUDITY, CASINO_ADS, SPAM, VIOLENCE, SAFE.

Some AI bots may appear harmless at first, but they edit their responses to include harmful content later.
That is why you need to analyze their profile names, profile pictures, and any other metadata (provided in context) to determine if they are safe or not.

If the name of the profile contains a mixture of Cyrillic and Latin/Unicode characters, it is likely a bot. Example: "Мария Знаkмлсьь", "Ульяна Вагuллина".
If the profile image contains NSFW content, it is likely a bot.
If the message is recruiting workers for a job, it is likely a bot.
If the message suggests "having fun", "making money", "easy cash", or similar phrases, it is likely a bot.
These are just some examples; you should use your best judgment to classify the content.

Analyze the content provided and respond with a single, clean JSON object containing two keys:
1. "category": The classification of the content.
2. "reason": A brief, one-sentence explanation for your classification.

Example input: "Hey check out this amazing offer at freespinscasino.win!"
Example output: {"category": "CASINO_ADS", "reason": "The message contains a link to a casino and promotes gambling."}

Example input: [An image containing a cat]
Example output: {"category": "SAFE", "reason": "The image contains a harmless picture of an animal."}

Now, classify the following content:
"""

gemini_client_instance = Client(api_key=GEMINI_API_KEY)
generation_config = types.GenerateContentConfig(
    safety_settings=[
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
            threshold=types.HarmBlockThreshold.BLOCK_NONE,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
            threshold=types.HarmBlockThreshold.BLOCK_NONE,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
            threshold=types.HarmBlockThreshold.BLOCK_NONE,
        ),
        types.SafetySetting(
            category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            threshold=types.HarmBlockThreshold.BLOCK_NONE,
        ),
    ]
)

# --- Core Bot Logic (Asynchronous) ---
async def classify_content(message_text, photo_bytes=None, profile_photo_bytes=None):
    """Sends content to Gemini and returns the classification (ASYNC)."""
    try:
        parts = [MODERATION_PROMPT]
        if message_text: parts.append(message_text)
        if photo_bytes: parts.append(Part.from_data(photo_bytes, mime_type='image/jpeg'))
        if profile_photo_bytes:
            parts.append("\n--- User's Profile Picture ---")
            parts.append(Part.from_data(profile_photo_bytes, mime_type='image/jpeg'))

        response = gemini_client_instance.models.generate_content(
            model="gemma-3-27b-it",
            contents=parts,
            generation_config=generation_config
        )
        cleaned_response = response.text.strip().replace('```json', '').replace('```', '').strip()
        logger.info(f"Gemini raw response: {cleaned_response}")
        return json.loads(cleaned_response)
    except Exception as e:
        logger.error(f"Error classifying content with Gemini: {e}", exc_info=True)
        return {"category": "ERROR", "reason": f"Failed to analyze content: {e}"}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The main handler for incoming messages (ASYNC)."""
    message = update.message
    if not message or message.chat.type not in ['group', 'supergroup'] or not message.from_user:
        return

    chat_id = message.chat_id
    user = message.from_user
    user_id = user.id
    user_name = user.full_name

    profile_photo_bytes = None
    try:
        profile_photos = await context.bot.get_user_profile_photos(user_id, limit=1)
        if profile_photos and profile_photos.photos:
            photo_file = await profile_photos.photos[0][-1].get_file()
            profile_photo_buffer = BytesIO()
            await photo_file.download_to_memory(profile_photo_buffer)
            profile_photo_bytes = profile_photo_buffer.getvalue()
    except Exception as e:
        logger.warning(f"Could not download profile photo for {user_name}: {e}")

    photo_bytes = None
    if message.photo:
        photo_file = await message.photo[-1].get_file()
        photo_buffer = BytesIO()
        await photo_file.download_to_memory(photo_buffer)
        photo_bytes = photo_buffer.getvalue()

    message_content = message.text or message.caption
    analysis_text = f"Username: {user_name}\nUser ID: {user_id}\nMessage: {message_content or '[No Text]'}"

    if not message_content and not photo_bytes: return

    logger.info(f"Analyzing message from {user_name} (ID: {user_id})")
    classification = await classify_content(analysis_text, photo_bytes, profile_photo_bytes)
    category = classification.get("category", "ERROR").upper()
    
    if category in ["NUDITY", "VIOLENCE", "CASINO_ADS", "SPAM"]:
        try:
            await message.delete()
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            logger.warning(f"BANNED user {user_name} for {category}.")
        except Exception as e:
            logger.error(f"Failed to ban user {user_name}: {e}")

# --- FastAPI Web Server ---
# The 'app' variable is now a FastAPI instance
app = FastAPI()
# We still create the bot_app instance from python-telegram-bot
bot_app = Application.builder().bot(Bot(token=TELEGRAM_BOT_TOKEN)).build()
bot_app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.CAPTION, handle_message))

@app.post('/webhook')
async def webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None)
):
    """ Webhook endpoint to receive updates from Telegram using FastAPI."""
    if x_telegram_bot_api_secret_token != WEBHOOK_SECRET_TOKEN:
        return Response(content="Unauthorized", status_code=403)
    
    try:
        update_data = await request.json()
        update = Update.de_json(update_data, bot_app.bot)
        await bot_app.process_update(update)
        return Response(content="ok", status_code=200)
    except Exception as e:
        logger.error(f"Error processing update: {e}", exc_info=True)
        return Response(content="Error", status_code=500)

@app.get('/')
def index():
    return "Telegram moderation bot is alive!", 200
