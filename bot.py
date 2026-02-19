"""
IEEE Research Paper Generator — Telegram Bot
"""

import asyncio
import logging
import os
import traceback

from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from config import BOT_TOKEN
from ai_content import generate_paper_content
from pdf_generator import generate_ieee_pdf

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Conversation states
TITLE, AUTHOR, PAGES = range(3)

# ─── Handlers ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point — greet user and ask for paper title."""
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) started the bot")
    context.user_data.clear()
    await update.message.reply_text(
        "👋 <b>Welcome to the IEEE Research Paper Generator!</b>\n\n"
        "I'll generate a fully formatted IEEE research paper PDF for you.\n\n"
        "📝 <b>Step 1 of 3:</b> Please send me your <b>paper title</b>.",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    return TITLE


async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the title and ask for author info."""
    title = update.message.text.strip()
    logger.info(f"Received title: {title}")

    if len(title) < 5:
        await update.message.reply_text(
            "⚠️ That title seems too short. Please enter a more descriptive paper title."
        )
        return TITLE

    context.user_data["title"] = title

    await update.message.reply_text(
        f"✅ Title saved!\n\n"
        f"👤 <b>Step 2 of 3:</b> Send your <b>author details</b> — paste each on a new line:\n\n"
        f"<code>Your Name\n"
        f"Department Name\n"
        f"College / University\n"
        f"City, Country\n"
        f"your@email.com</code>\n\n"
        f"<i>Example:</i>\n"
        f"<code>Suriya D\n"
        f"Department of Artificial Intelligence and Data Science\n"
        f"Meenakshi Sundararajan Engineering College\n"
        f"Chennai, India\n"
        f"303suriya@gmail.com</code>",
        parse_mode="HTML",
    )
    return AUTHOR


async def receive_author(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Parse the multiline author block and ask for page count."""
    import re as _re
    raw = update.message.text.strip()

    if not raw:
        await update.message.reply_text("⚠️ Please send your author details.")
        return AUTHOR

    # Split on newlines; each line is one field
    lines = [l.strip() for l in raw.splitlines() if l.strip()]

    # Extract email from any line that looks like an email, then remove it
    email = ""
    clean_lines = []
    for line in lines:
        if _re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', line):
            email = line
        else:
            clean_lines.append(line)
    lines = clean_lines

    # Assign fields by position: name, dept, uni, city (extras appended to city)
    name = lines[0] if len(lines) > 0 else "Author"
    dept = lines[1] if len(lines) > 1 else "Department of Engineering"
    uni  = lines[2] if len(lines) > 2 else "University"
    city = ", ".join(lines[3:]) if len(lines) > 3 else "India"

    # Sanitize — strip chars that break JSON strings inside AI prompts
    def _clean(s): return _re.sub(r'["\'\\\t]', ' ', s).strip()[:80]
    name  = _clean(name)
    dept  = _clean(dept)
    uni   = _clean(uni)
    city  = _clean(city)[:40]
    email = _clean(email)[:80] if email else f"{name.lower().replace(' ', '.')}@university.edu"

    context.user_data["author_name"]  = name
    context.user_data["author_dept"]  = dept
    context.user_data["author_uni"]   = uni
    context.user_data["author_city"]  = city
    context.user_data["author_email"] = email
    logger.info(f"Author parsed: {name} | {dept} | {uni} | {city} | {email}")

    await update.message.reply_text(
        f"✅ Author details saved!\n"
        f"👤 <b>{name}</b>\n"
        f"🏫 {dept}\n"
        f"🏛 {uni}\n"
        f"📍 {city}\n"
        f"📧 {email}\n\n"
        f"📄 <b>Step 3 of 3:</b> How many pages should the paper be?\n"
        f"<i>(Enter a number between 4 and 20)</i>",
        parse_mode="HTML",
    )
    return PAGES


def make_progress_bar(pct: int, width: int = 20) -> str:
    """Build a visual block progress bar string."""
    filled = int(width * pct / 100)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct}%"


async def animated_progress(status_msg, title: str, stop_event: asyncio.Event, result_holder: list):
    """
    Background task: animates a progress bar from 0% to 100%.
    - 0–80%  → AI is writing content  (takes most of the time)
    - 80–95% → Rendering PDF
    - 95–100%→ Finalizing
    Stops when stop_event is set. result_holder[0] will be set to final % when done.
    """
    # Phase timings (percent_target, seconds_per_step, step_size)
    phases = [
        # AI writing phase: 0→80% over ~50s (step every 2s = 25 steps of ~3.2%)
        (80,  2.0, 3),
        # Rendering phase: 80→95% over ~10s
        (95,  1.5, 2),
        # Finalizing: 95→99%
        (99,  1.0, 1),
    ]

    pct = 0
    labels = {
        (0,  80): "🤖 AI Writing Paper...",
        (80, 95): "📐 Rendering IEEE PDF...",
        (95, 100): "✨ Finalizing...",
    }

    def get_label(p):
        for (lo, hi), lbl in labels.items():
            if lo <= p < hi:
                return lbl
        return "✨ Finalizing..."

    for (target, delay, step) in phases:
        while pct < target:
            if stop_event.is_set():
                return
            pct = min(pct + step, target)
            bar = make_progress_bar(pct)
            label = get_label(pct)
            try:
                await status_msg.edit_text(
                    f"⚙️ <b>Generating IEEE Research Paper</b>\n\n"
                    f"📌 <i>{title}</i>\n\n"
                    f"{label}\n"
                    f"<code>{bar}</code>",
                    parse_mode="HTML",
                )
            except Exception:
                pass  # Ignore "message not modified" errors
            await asyncio.sleep(delay)

    # Hold at 99% until stop_event fires
    while not stop_event.is_set():
        await asyncio.sleep(0.5)


async def receive_pages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate page count, then generate the paper with a live progress bar."""
    text = update.message.text.strip()

    try:
        pages = int(text)
    except ValueError:
        await update.message.reply_text(
            "⚠️ Please enter a valid number (e.g., 6, 8, 10)."
        )
        return PAGES

    if pages < 4 or pages > 20:
        await update.message.reply_text(
            "⚠️ Please enter a number between <b>4</b> and <b>20</b> pages.",
            parse_mode="HTML",
        )
        return PAGES

    title       = context.user_data.get("title", "Research Paper")
    author_name = context.user_data.get("author_name", "Author")
    author_dept = context.user_data.get("author_dept", "Department of Engineering")
    author_uni  = context.user_data.get("author_uni", "University")
    author_city = context.user_data.get("author_city", "India")
    author_email = context.user_data.get("author_email", f"{author_name.lower().replace(' ', '.')}@university.edu")

    # Build a clean IEEE author dict — always override whatever the AI generates
    clean_author = {
        "name":       author_name,
        "department": author_dept,
        "university": author_uni,
        "city":       author_city,
        "email":      author_email,
    }

    # Send initial status message with 0% bar
    bar0 = make_progress_bar(0)
    status_msg = await update.message.reply_text(
        f"⚙️ <b>Generating IEEE Research Paper</b>\n\n"
        f"📌 <i>{title}</i>\n\n"
        f"🤖 AI Writing Paper...\n"
        f"<code>{bar0}</code>",
        parse_mode="HTML",
    )

    stop_event = asyncio.Event()
    result_holder = [0]

    # Start the animated progress bar as a background task
    progress_task = asyncio.create_task(
        animated_progress(status_msg, title, stop_event, result_holder)
    )

    pdf_path = None
    try:
        # Run AI generation (this is the slow part)
        paper_data = await asyncio.get_event_loop().run_in_executor(
            None, generate_paper_content, title, pages, author_name, author_uni
        )

        # Always override the AI-generated authors with clean user-provided data
        paper_data["authors"] = [clean_author]

        # Run PDF rendering
        pdf_path = await asyncio.get_event_loop().run_in_executor(
            None, generate_ieee_pdf, paper_data
        )

        # Stop the progress bar and show 100%
        stop_event.set()
        await progress_task

        bar100 = make_progress_bar(100)
        try:
            await status_msg.edit_text(
                f"⚙️ <b>Generating IEEE Research Paper</b>\n\n"
                f"📌 <i>{title}</i>\n\n"
                f"✅ Complete!\n"
                f"<code>{bar100}</code>",
                parse_mode="HTML",
            )
        except Exception:
            pass

        await asyncio.sleep(0.5)

        # Send the PDF
        safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in title)
        safe_title = safe_title[:50].strip().replace(" ", "_")
        filename = f"IEEE_{safe_title}.pdf"

        await status_msg.delete()

        with open(pdf_path, "rb") as pdf_file:
            await update.message.reply_document(
                document=pdf_file,
                filename=filename,
                caption=(
                    f"✅ <b>Your IEEE Research Paper is ready!</b>\n\n"
                    f"📌 <b>Title:</b> {title}\n"
                    f"📄 <b>Pages:</b> ~{pages}\n\n"
                    f"🔁 Send /start to generate another paper."
                ),
                parse_mode="HTML",
            )

    except Exception as e:
        stop_event.set()
        try:
            await progress_task
        except Exception:
            pass
        logger.error(f"Error generating paper: {e}", exc_info=True)
        err_msg = str(e)[:300].replace("<", "&lt;").replace(">", "&gt;")
        try:
            await status_msg.edit_text(
                f"❌ <b>An error occurred while generating your paper.</b>\n\n"
                f"Error: <code>{err_msg}</code>\n\n"
                f"Please try again with /start.",
                parse_mode="HTML",
            )
        except Exception:
            await update.message.reply_text(
                f"❌ Error: {err_msg[:200]}\n\nPlease try /start again."
            )
    finally:
        if pdf_path and os.path.exists(pdf_path):
            try:
                os.unlink(pdf_path)
            except Exception:
                pass

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation."""
    await update.message.reply_text(
        "❌ Cancelled. Send /start to begin again.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log all errors."""
    logger.error("Exception while handling update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ An unexpected error occurred. Please try /start again."
            )
        except Exception:
            pass


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help message."""
    await update.message.reply_text(
        "📖 <b>IEEE Research Paper Generator Bot</b>\n\n"
        "<b>Commands:</b>\n"
        "/start — Generate a new IEEE paper\n"
        "/cancel — Cancel current operation\n"
        "/help — Show this message\n\n"
        "<b>How it works:</b>\n"
        "1. Send /start\n"
        "2. Enter your paper title\n"
        "3. Enter your name and college\n"
        "4. Enter desired page count (4–20)\n"
        "5. Receive your IEEE-formatted PDF! 🎓\n\n"
        "<b>Features:</b>\n"
        "• Two-column IEEE layout\n"
        "• Times New Roman fonts\n"
        "• Your real name and affiliation\n"
        "• All standard sections (Abstract → References)\n"
        "• IEEE-style table and citations",
        parse_mode="HTML",
    )


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    """Start the bot."""
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            TITLE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)],
            AUTHOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_author)],
            PAGES:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_pages)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("help", help_command))
    app.add_error_handler(error_handler)

    logger.info("🚀 IEEE Paper Generator Bot is running...")
    # drop_pending_updates=True clears any old messages queued before bot started
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
