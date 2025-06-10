import os
import logging
import json
from io import BytesIO
from flask import Flask, request, Response
from telegram import Update, Bot
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from google.genai.types import Part
from google.genai import types
from google import genai
import asyncio
from a2wsgi import ASGIMiddleware # <<< ADDED: Import the ASGI adapter

# --- Configuration and Initialization ---

# Securely load environment variables
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
WEBHOOK_SECRET_TOKEN = os.environ.get('WEBHOOK_SECRET_TOKEN')

# Validate that all required variables are set
if not all([TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, WEBHOOK_SECRET_TOKEN]):
    raise ValueError("Missing required environment variables: TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, WEBHOOK_SECRET_TOKEN")

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Gemini Model Configuration ---

# <<< FIXED: Corrected prompt with accurate information about User IDs.
MODERATION_PROMPT = """
You are an AI content moderator for a Telegram chat group. Your task is to classify incoming messages
(text and images), user profiles (name, photo), and user metadata into one of the following categories:
NUDITY, CASINO_ADS, SPAM, VIOLENCE, SAFE.

Some AI bots may appear harmless at first, but they edit their responses to include harmful content later.
Therefore, you must analyze all available context to determine if they are safe or not.

CRITERIA FOR BOTS/SPAM:
- PROFILE NAME: Names with a strange mix of Cyrillic and Latin characters (e.g., "Мария Знаkмлсьь") are highly suspicious.
- PROFILE IMAGE: Images containing nudity, suggestive content, or advertising are strong indicators of a bot.
- MESSAGE CONTENT: Messages suggesting "having fun", "making money", "winning", or containing suspicious links are likely from bots or spammers. Also, promoting fishy jobs, "easy money grabs", etc. is considered spam.
- USER ID: All Telegram User IDs are large integers. This is just for context.

Analyze the content provided (user metadata, message text, and any images) and respond with a single, clean JSON object
containing two keys: "category" and "reason".

Example input: Message from "John Doe" (ID: 12345): "Hey check out this amazing offer at freespinscasino.top!"
Example output: {"category": "CASINO_ADS", "reason": "The message contains a link to a casino and promotes gambling."}

Example input: An image of a cat from "KittyLover" (ID: 54321)
Example output: {"category": "SAFE", "reason": "The image contains a harmless picture of an animal."}

Now, classify the following content:
"""

# Using a fast and capable model suitable for this task.
client = genai.Client(api_key=GEMINI_API_KEY)

# <<< ADDED: Safety settings are crucial for a moderation bot.
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

# --- Core Bot Logic ---

async def classify_content(message_text, photo_bytes=None, profile_photo_bytes=None):
    """Sends content to Gemini and returns the classification using the Client API."""
    try:
        parts = [MODERATION_PROMPT]

        # Add all available context to the request parts
        if message_text:
            parts.append(message_text)
        if photo_bytes:
            parts.append(Part.from_data(photo_bytes, mime_type='image/jpeg'))
        if profile_photo_bytes:
            parts.append("\n--- User's Profile Picture ---")
            parts.append(Part.from_data(profile_photo_bytes, mime_type='image/jpeg'))

        # <<< FIXED: The API call now uses the Client interface.
        # Note: We use the `_async` version to not block our async bot.
        # The correct parameter name for the config is `generation_config`.
        response = client.models.generate_content(
            model="models/gemma-3-27b-it", # Correct model path for API calls
            contents=parts,
            config=generation_config
        )
        
        # Clean up the response from markdown code blocks
        cleaned_response = response.text.strip().replace('```json', '').replace('```', '').strip()
        
        logger.info(f"Gemini raw response: {cleaned_response}")
        result = json.loads(cleaned_response)
        return result
    
    except Exception as e:
        logger.error(f"Error classifying content with Gemini: {e}", exc_info=True)
        return {"category": "ERROR", "reason": f"Failed to analyze content due to: {e}"}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The main handler for incoming messages."""
    message = update.message

    # A guard clause to ensure the bot only operates in group chats.
    if not message or message.chat.type not in ['group', 'supergroup']:
        logger.info(f"Ignoring message because it's not from a group chat (type: {message.chat.type})")
        return
        
    
    if not message.from_user:
        return

    chat_id = message.chat_id
    user = message.from_user
    user_id = user.id
    user_name = user.full_name

    # --- Data Collection ---
    profile_photo_bytes = None # <<< FIXED: Initialize to None to prevent NameError
    try:
        # <<< FIXED: Added 'await' for the async call
        profile_photos = await user.get_profile_photos(limit=1)
        if profile_photos and profile_photos.photos:
            profile_photo_file = await profile_photos.photos[0][-1].get_file()
            profile_photo_buffer = BytesIO()
            await profile_photo_file.download_to_memory(profile_photo_buffer)
            profile_photo_bytes = profile_photo_buffer.getvalue()
            logger.info(f"Profile photo for {user_name} downloaded.")
    except Exception as e:
        logger.warning(f"Could not download profile photo for {user_name}: {e}")

    photo_bytes = None
    if message.photo:
        photo_file = await message.photo[-1].get_file()
        photo_buffer = BytesIO()
        await photo_file.download_to_memory(photo_buffer)
        photo_bytes = photo_buffer.getvalue()
        logger.info(f"Processing image from {user_name} in chat {chat_id}")

    # Construct the text part for Gemini, including user metadata
    message_content = message.text or message.caption
    analysis_text = f"Username: {user_name}\nUser ID: {user_id}\nMessage: {message_content or '[No Text]'}"

    if not message_content and not photo_bytes:
        logger.info("Ignoring message with no text or photo.")
        return

    logger.info(f"Analyzing message from {user_name} (ID: {user_id}) in chat {chat_id}")
    
    classification = await classify_content(analysis_text, photo_bytes, profile_photo_bytes)
    category = classification.get("category", "ERROR").upper()
    reason = classification.get("reason", "No reason provided.")

    logger.info(f"Message from {user_name} classified as {category}. Reason: {reason}")

    # --- Moderation Action ---
    if category in ["NUDITY", "VIOLENCE", "CASINO_ADS", "SPAM"]:
        try:
            await message.delete()
            await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"User {user_name} has been banned. Reason: Content classified as {category}."
            )
            logger.warning(f"BANNED user {user_name} for {category}.")
        except Exception as e:
            logger.error(f"Failed to ban user {user_name}: {e}. The bot might be missing admin permissions.")


# --- Flask Web Server ---
app = Flask(__name__)
bot_app = Application.builder().bot(Bot(token=TELEGRAM_BOT_TOKEN)).build()
bot_app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.CAPTION, handle_message))

@app.route('/webhook', methods=['POST'])
async def webhook():
    """Webhook endpoint to receive updates from Telegram (ASYNC)."""
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET_TOKEN:
        return Response("Unauthorized", status=403)
    
    try:
        update = Update.de_json(await request.get_json(), bot_app.bot)
        await bot_app.process_update(update)
        return Response('ok', status=200)
    except Exception as e:
        logger.error(f"Error processing update: {e}", exc_info=True)
        return Response('Error', status=500)

@app.route('/')
def index():
    return "Telegram moderation bot is alive!", 200

# <<< ADDED: Wrap the Flask app with the ASGI middleware
asgi_app = ASGIMiddleware(app)
