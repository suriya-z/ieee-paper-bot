"""
IEEE Research Paper Generator — Telegram Bot
"""

import asyncio
import logging
import os
import traceback

from telegram import Update, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from config import BOT_TOKEN, OWNER_ID
from ai_content import generate_paper_content
from pdf_generator import generate_ieee_pdf
from premium import (
    generate_key, redeem_key, is_premium, list_keys, delete_key,
    FREE_PAGE_LIMIT
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Conversation states
TITLE, AUTHOR, PAGES, MODE = range(4)


def owner_only(func):
    """Decorator: blocks non-owners with a silent rejection."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text("⛔ This command is owner-only.")
            return
        return await func(update, context)
    wrapper.__name__ = func.__name__
    return wrapper

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
        f"📄 <b>Step 3 of 4:</b> How many pages should the paper be?\n"
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

    # Free users capping (Owner gets unlimited pages)
    user_id = update.effective_user.id
    has_premium = (user_id == OWNER_ID) or is_premium(user_id)

    if pages > FREE_PAGE_LIMIT and not has_premium:
        await update.message.reply_text(
            f"⛔ <b>Premium Required</b>\n\n"
            f"Free users can generate up to <b>{FREE_PAGE_LIMIT} pages</b>.\n"
            f"You requested <b>{pages} pages</b>.\n\n"
            f"🔑 Redeem a premium key with:\n<code>/redeem SURIYA-XXXXXXXXXX</code>\n\n"
            f"💬 Contact the owner to purchase a key.",
            parse_mode="HTML",
        )
        return PAGES

    context.user_data["pages"] = pages

    # Show Anti-AI-detection mode selector
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🕵️ Anti-Detection: ON",  callback_data="antiai_on"),
            InlineKeyboardButton("📄 Standard: OFF",        callback_data="antiai_off"),
        ]
    ])
    await update.message.reply_text(
        f"✅ <b>{pages} pages</b> selected!\n\n"
        f"🕵️ <b>Step 4 of 4:</b> Anti-AI-Detection Mode\n"
        f"<i>Humanizes the writing to reduce AI detection scores (GPTZero, Turnitin).</i>\n\n"
        f"Choose a mode:",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    return MODE


async def receive_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle Anti-AI-detection mode button and run paper generation."""
    query = update.callback_query
    await query.answer()

    anti_detection = (query.data == "antiai_on")
    mode_label = "🕵️ Anti-Detection ON" if anti_detection else "📄 Standard Mode"

    title        = context.user_data.get("title", "Research Paper")
    pages        = context.user_data.get("pages", 6)
    author_name  = context.user_data.get("author_name", "Author")
    author_dept  = context.user_data.get("author_dept", "Department of Engineering")
    author_uni   = context.user_data.get("author_uni", "University")
    author_city  = context.user_data.get("author_city", "India")
    author_email = context.user_data.get("author_email",
                       f"{author_name.lower().replace(' ', '.')}@university.edu")

    clean_author = {
        "name":       author_name,
        "department": author_dept,
        "university": author_uni,
        "city":       author_city,
        "email":      author_email,
    }

    await query.edit_message_text(
        f"✅ Mode: <b>{mode_label}</b>\n\n⚙️ Starting generation...",
        parse_mode="HTML",
    )

    bar0 = make_progress_bar(0)
    status_msg = await query.message.reply_text(
        f"⚙️ <b>Generating IEEE Research Paper</b>\n\n"
        f"📌 <i>{title}</i>\n\n"
        f"🤖 AI Writing Paper...\n"
        f"<code>{bar0}</code>",
        parse_mode="HTML",
    )

    stop_event    = asyncio.Event()
    result_holder = [0]
    progress_task = asyncio.create_task(
        animated_progress(status_msg, title, stop_event, result_holder)
    )

    pdf_path = None
    try:
        paper_data = await asyncio.get_event_loop().run_in_executor(
            None, generate_paper_content, title, pages, author_name, author_uni, anti_detection
        )
        paper_data["authors"] = [clean_author]

        pdf_path = await asyncio.get_event_loop().run_in_executor(
            None, generate_ieee_pdf, paper_data
        )

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
        await status_msg.delete()

        safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in title)
        safe_title = safe_title[:50].strip().replace(" ", "_")
        filename   = f"IEEE_{safe_title}.pdf"

        with open(pdf_path, "rb") as pdf_file:
            await query.message.reply_document(
                document=pdf_file,
                filename=filename,
                caption=(
                    f"✅ <b>Your IEEE Research Paper is ready!</b>\n\n"
                    f"📌 <b>Title:</b> {title}\n"
                    f"📄 <b>Pages:</b> ~{pages}\n"
                    f"🔒 <b>Mode:</b> {mode_label}\n\n"
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
            await query.message.reply_text(
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


# ─── Owner commands ────────────────────────────────────────────────────────────

@owner_only
async def cmd_genkey(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate 1 or N premium keys. Usage: /genkey [count]"""
    count = 1
    if context.args:
        try:
            count = max(1, min(int(context.args[0]), 50))
        except ValueError:
            pass

    keys = [generate_key() for _ in range(count)]
    keys_text = "\n".join(f"<code>{k}</code>" for k in keys)
    await update.message.reply_text(
        f"🔑 <b>{count} Premium Key{'s' if count > 1 else ''} Generated:</b>\n\n{keys_text}",
        parse_mode="HTML",
    )


@owner_only
async def cmd_keys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all generated keys and their status."""
    keys = list_keys()
    if not keys:
        await update.message.reply_text("📦 No keys generated yet. Use /genkey to create some.")
        return

    lines = []
    for entry in keys:
        status = f"✅ Used by <code>{entry['used_by']}</code>" if entry["used"] else "⚪️ Unused"
        lines.append(f"<code>{entry['key']}</code> — {status}")

    text = "\n".join(lines)
    await update.message.reply_text(
        f"📊 <b>All Premium Keys ({len(keys)}):</b>\n\n{text}",
        parse_mode="HTML",
    )


@owner_only
async def cmd_delkey(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a key. Usage: /delkey SURIYA-XXXXXXXXXX"""
    if not context.args:
        await update.message.reply_text("Usage: <code>/delkey SURIYA-XXXXXXXXXX</code>", parse_mode="HTML")
        return
    key = context.args[0].strip().upper()
    if delete_key(key):
        await update.message.reply_text(f"✅ Key <code>{key}</code> deleted.", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ Key <code>{key}</code> not found.", parse_mode="HTML")


# ─── User commands ─────────────────────────────────────────────────────────────

async def cmd_redeem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Redeem a premium key. Usage: /redeem SURIYA-XXXXXXXXXX"""
    if not context.args:
        await update.message.reply_text(
            "🔑 <b>Redeem a Premium Key</b>\n\nUsage: <code>/redeem SURIYA-XXXXXXXXXX</code>",
            parse_mode="HTML",
        )
        return
    key = context.args[0].strip().upper()
    user_id = update.effective_user.id
    success, msg = redeem_key(key, user_id)
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_premium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check premium status."""
    user_id = update.effective_user.id
    
    if user_id == OWNER_ID:
        await update.message.reply_text(
            "👑 <b>Owner Access</b>\nYou have lifetime premium privileges.",
            parse_mode="HTML",
        )
        return

    if is_premium(user_id):
        await update.message.reply_text(
            "⭐ <b>You have Premium access!</b>\nYou can generate up to <b>20 pages</b>.",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            f"🔓 <b>Free account</b> — limited to <b>{FREE_PAGE_LIMIT} pages</b>.\n\n"
            f"🔑 Redeem a key with: <code>/redeem SURIYA-XXXXXXXXXX</code>",
            parse_mode="HTML",
        )



def main() -> None:
    """Start the bot."""
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            TITLE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)],
            AUTHOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_author)],
            PAGES:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_pages)],
            MODE:   [CallbackQueryHandler(receive_mode, pattern="^antiai_(on|off)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("help", help_command))
    # Owner commands
    app.add_handler(CommandHandler("genkey", cmd_genkey))
    app.add_handler(CommandHandler("keys", cmd_keys))
    app.add_handler(CommandHandler("delkey", cmd_delkey))
    # User commands
    app.add_handler(CommandHandler("redeem", cmd_redeem))
    app.add_handler(CommandHandler("premium", cmd_premium))
    app.add_error_handler(error_handler)

    logger.info("🚀 IEEE Paper Generator Bot is running...")
    # drop_pending_updates=True clears any old messages queued before bot started
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
