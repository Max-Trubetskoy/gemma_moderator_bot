# AI-Powered Telegram Chat Moderator
This repository contains the complete source code for a serverless, AI-powered moderation bot for Telegram groups. The bot uses Google's Gemma 3 model via the Gemini API to analyze messages and user profiles in real-time, automatically detecting and removing spam, scams, and inappropriate content.This project was built to be a robust, intelligent, and virtually free solution for keeping online communities safe.

## Features
- Multimodal Analysis: Simultaneously analyzes message text, user profile names, and user profile pictures to make context-aware moderation decisions.
- Proactive Moderation: Silently monitors all group activity and takes action without needing to be called or mentioned.
- Automatic Actions: Deletes offending messages and bans the user from the group upon detecting a violation.
- Serverless & Cost-Effective: Built to run on Google Cloud Run, leveraging the "Always Free" tier for minimal to zero operational cost for most communities.
- High-Performance: Uses a modern Python web stack (FastAPI & Uvicorn) for a fast, asynchronous, and scalable backend.

## Tech Stack
- Language: Python 3.11
- AI Model: Google Gemma 3 27B (Instruction-Tuned) via the Gemini API
- Web Framework: FastAPI
- Web Server: Uvicorn
- Hosting Platform: Google Cloud Run
- Containerization: Docker
- Project Structure
- The repository is structured simply:
```
├── bot.py              # The main FastAPI application and bot logic
├── Dockerfile          # Instructions to build the container image
└── requirements.txt    # Python dependencies
```
## Setup and Deployment Guide
Follow these steps to deploy your own instance of the moderator bot.

### Prerequisites
- A Telegram Bot Token. Get this from @BotFather on Telegram.
- A Google Cloud Project with billing enabled. New users get a generous free credit.
- The gcloud command-line tool installed and configured on your local machine.

### Step 1: Clone the Repository
Clone this repository to your local machine:
```
git clone <your-repository-url>
cd <repository-directory>
```
### Step 2: Deploy to Google Cloud Run
This project is configured for one-step deployment from the source code. Cloud Run will automatically use the ```Dockerfile``` to build and deploy your container.

Run the following command from your terminal:
```
gcloud run deploy gemma-moderator-bot \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --set-env-vars="TELEGRAM_BOT_TOKEN=YOUR_TOKEN_HERE" \
  --set-env-vars="GEMINI_API_KEY=YOUR_API_KEY_HERE" \
  --set-env-vars="WEBHOOK_SECRET_TOKEN=A_STRONG_RANDOM_SECRET_HERE"
```
#### Important Notes:

- Replace the placeholder values for the environment variables with your actual credentials.
- Memory: We explicitly set --memory 1Gi. This is crucial for giving the bot enough RAM to download and process images without crashing.
- Region: Feel free to change us-central1 to your preferred Google Cloud region.

### Step 3: Set the Telegram Webhook
Once the deployment is successful, Google Cloud Run will provide you with a public URL for your service. You need to tell Telegram to send all bot updates to this URL.

```
# Execute the following command, replacing the placeholders with your bot token and the URL from Cloud Run:# Get your service URL
SERVICE_URL=$(gcloud run services describe gemma-moderator-bot --platform managed --region us-central1 --format 'value(status.url)')

# Set the webhook
curl "https://api.telegram.org/bot<YOUR_TELEGRAM_BOT_TOKEN>/setWebhook?url=${SERVICE_URL}/webhook&secret_token=<YOUR_WEBHOOK_SECRET_TOKEN>"
```

### Step 4: Configure the Bot in Telegram
For the bot to function correctly, you must perform two final configuration steps in your Telegram group:
- Make the Bot an Admin: In your group settings, add the bot as an administrator and grant it at least the "Delete Messages" and "Ban Users" permissions.
- Disable Privacy Mode: Chat with ```@BotFather```, go to ```/mybots```, select your bot, go to ```Bot Settings``` -> ```Group Privacy```, and click "Turn off". This allows the bot to see all messages in the group, not just commands.

Your AI moderator is now live!
