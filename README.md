# 📄 IEEE Research Paper Generator Bot

A Telegram bot that generates fully formatted IEEE conference papers as PDFs using AI.

## Features
- Two-column IEEE A4 layout
- AI-generated content (abstract, introduction, related work, methodology, results, conclusion)
- Proper section headings, equation formatting, and reference list
- Scales to user-specified page count (4–20 pages)
- PDF delivered instantly in Telegram chat

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Create `.env` file
```env
BOT_TOKEN=your_telegram_bot_token
APIMART_API_KEY=your_apimart_key
APIMART_BASE_URL=https://api.apimart.ai/v1
AI_MODEL=gemini-2.5-pro
```

### 4. Run
```bash
python bot.py
```

## Deploy (Railway)
1. Push to GitHub
2. Connect repo on [railway.app](https://railway.app)
3. Add environment variables in Railway dashboard
4. Deploy — it auto-detects Python and uses the `Procfile`

## Usage
1. `/start` — Begin paper generation
2. Enter paper title
3. Enter author details (name, department, college, city, email — one per line)
4. Enter page count (4–20)
5. Wait ~30–60 seconds → receive PDF

## Stack
- `python-telegram-bot` — Telegram API
- `reportlab` — PDF generation
- `apimart.ai` — Gemini 2.5 Pro for content generation
