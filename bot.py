"""
Fanatec Stock Searcher — Telegram Bot
Monitors the Fanatec Certified Refurbished page and sends alerts
when new products appear or availability changes.
"""

import asyncio
import html
from datetime import datetime, timezone
from functools import wraps
from typing import Callable

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    filters,
)

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_ADMIN_USER_ID,
    CHECK_INTERVAL_MINUTES,
    FANATEC_URL,
    validate_config,
    logger,
)
from database import Database, Product
from scraper import scrape_products


# ── Globals ──────────────────────────────────────────────────────────
db = Database()


# ── Authorization decorator ──────────────────────────────────────────

def admin_only(func: Callable):
    """Decorator to restrict commands to the configured admin user."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id if update.effective_user else 0
        if user_id != TELEGRAM_ADMIN_USER_ID:
            logger.warning(
                f"Unauthorized access attempt by user {user_id} "
                f"(@{update.effective_user.username if update.effective_user else 'unknown'})"
            )
            await update.message.reply_text("⛔ Unauthorized. This bot is private.")
            return
        return await func(update, context)
    return wrapper


# ── Telegram message formatting ──────────────────────────────────────

def _format_product_alert(product: Product, alert_type: str, old_product: Product = None, watched_keywords: list[str] = None) -> str:
    """Format a product alert message in HTML."""
    name = html.escape(product.name)
    price = html.escape(product.price) if product.price else "N/A"
    orig = html.escape(product.original_price) if product.original_price else ""
    avail = html.escape(product.availability)
    url = product.product_url

    if alert_type == "watchlist":
        emoji = "🚨🚨🚨"
        title = "WATCHED PRODUCT FOUND!"
    elif alert_type == "new":
        emoji = "🆕"
        title = "New Product Found!"
    elif alert_type == "available":
        emoji = "✅"
        title = "Product Now Available!"
    elif alert_type == "price_change":
        emoji = "💰"
        title = "Price Changed!"
    elif alert_type == "unavailable":
        emoji = "⚠️"
        title = "Product Became Unavailable"
    elif alert_type == "disappeared":
        emoji = "🗑️"
        title = "Product Removed from Page"
    else:
        emoji = "🔔"
        title = "Product Update"

    msg = f"{emoji} <b>{title}</b>\n\n"

    if alert_type == "watchlist":
        msg += "⚡ <b>This matches your watchlist!</b>\n"
        if watched_keywords:
            kws = ", ".join(f'"<code>{html.escape(k)}</code>"' for k in watched_keywords)
            msg += f"🔎 Matched: {kws}\n\n"

    msg += f"📦 <b>{name}</b>\n"

    if price:
        msg += f"💶 <b>{price}</b>"
        if orig:
            msg += f"  <s>{orig}</s>"
        msg += "\n"

    msg += f"📊 Status: <b>{avail}</b>\n"

    if old_product and alert_type in ("available", "unavailable"):
        old_avail = html.escape(old_product.availability)
        msg += f"   ↳ was: <i>{old_avail}</i>\n"

    if old_product and alert_type == "price_change":
        old_price = html.escape(old_product.price)
        msg += f"   ↳ was: <i>{old_price}</i>\n"

    if url:
        msg += f"\n🔗 <a href=\"{url}\">View on Fanatec</a>"

    if alert_type == "watchlist":
        msg += "\n\n🏃 <b>GO GO GO!</b>"

    return msg


def _format_status_message(products: list[Product], last_scrape: dict = None) -> str:
    """Format the /status response."""
    if not products:
        return "📭 <b>No products tracked yet.</b>\n\nUse /force_check to trigger a scan."

    available = [p for p in products if p.is_available()]
    unavailable = [p for p in products if not p.is_available()]

    msg = f"📊 <b>Fanatec Refurbished Monitor</b>\n"
    msg += f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"📦 Total tracked: <b>{len(products)}</b>\n"
    msg += f"✅ Available: <b>{len(available)}</b>\n"
    msg += f"❌ Unavailable: <b>{len(unavailable)}</b>\n"

    if last_scrape:
        msg += f"🕐 Last check: <code>{last_scrape.get('timestamp', 'N/A')[:19]}</code>\n"
        msg += f"   Status: {last_scrape.get('status', 'N/A')}\n"

    msg += f"\n━━━━━━━━━━━━━━━━━━━━━━━━━\n"

    if available:
        msg += f"\n✅ <b>Available:</b>\n"
        for p in available:
            name = html.escape(p.name)
            price = html.escape(p.price) if p.price else "?"
            url = p.product_url
            msg += f"  • <a href=\"{url}\">{name}</a> — <b>{price}</b>\n"

    if unavailable:
        msg += f"\n❌ <b>Unavailable:</b>\n"
        for p in unavailable:
            name = html.escape(p.name)
            msg += f"  • {name} — <i>{html.escape(p.availability)}</i>\n"

    return msg


# ── Core scrape-and-compare logic ────────────────────────────────────

async def check_and_notify(context: ContextTypes.DEFAULT_TYPE = None, chat_id: int = None) -> str:
    """
    Run the scraper, compare with DB, send alerts, update DB.
    Returns a summary string.
    """
    target_chat_id = chat_id or TELEGRAM_ADMIN_USER_ID
    bot = context.bot if context else None

    try:
        logger.info("Starting scrape cycle...")
        products = await scrape_products()

        if not products:
            db.log_scrape("error", 0, "No products scraped")
            summary = "⚠️ Scrape returned 0 products. Site may be down or blocked."
            if bot:
                await bot.send_message(
                    chat_id=target_chat_id,
                    text=summary,
                )
            return summary

        db.log_scrape("success", len(products))
        alerts: list[str] = []          # Regular alerts
        priority_alerts: list[str] = []  # Watchlist alerts (sent first)
        current_urls = {p.product_url for p in products}

        # ── Process each scraped product ────────────────────────
        for product in products:
            action, old_product = db.upsert_product(product)

            # Check watchlist match
            matched_keywords = db.matches_watchlist(product.name)

            if action == "new":
                if matched_keywords and product.is_available():
                    # 🚨 Priority: watched product appeared!
                    alert_msg = _format_product_alert(
                        product, "watchlist", watched_keywords=matched_keywords
                    )
                    priority_alerts.append(alert_msg)
                else:
                    alert_msg = _format_product_alert(product, "new")
                    alerts.append(alert_msg)

            elif action == "updated" and old_product:
                # Availability changed
                if old_product.availability != product.availability:
                    if product.is_available() and not old_product.is_available():
                        if matched_keywords:
                            # 🚨 Priority: watched product became available!
                            alert_msg = _format_product_alert(
                                product, "watchlist", old_product,
                                watched_keywords=matched_keywords,
                            )
                            priority_alerts.append(alert_msg)
                        else:
                            alert_msg = _format_product_alert(product, "available", old_product)
                            alerts.append(alert_msg)
                    elif not product.is_available() and old_product.is_available():
                        alert_msg = _format_product_alert(product, "unavailable", old_product)
                        alerts.append(alert_msg)

                # Price changed
                if old_product.price != product.price:
                    alert_msg = _format_product_alert(product, "price_change", old_product)
                    alerts.append(alert_msg)

        # ── Check for disappeared products ──────────────────────
        disappeared = db.get_disappeared_products(current_urls)
        for dp in disappeared:
            alert_msg = _format_product_alert(dp, "disappeared")
            alerts.append(alert_msg)
            db.remove_product(dp.product_url)

        # ── Send priority alerts first ──────────────────────────
        all_alerts = priority_alerts + alerts
        if bot and all_alerts:
            for alert in all_alerts:
                try:
                    await bot.send_message(
                        chat_id=target_chat_id,
                        text=alert,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=False,
                    )
                    await asyncio.sleep(0.5)  # Respect Telegram rate limits
                except Exception as e:
                    logger.error(f"Failed to send alert: {e}")

        summary = (
            f"✅ Scrape complete: {len(products)} product(s) found, "
            f"{len(all_alerts)} alert(s) sent"
        )
        if priority_alerts:
            summary += f" (🚨 {len(priority_alerts)} watchlist match!)"
        summary += "."
        logger.info(summary)
        return summary

    except Exception as e:
        error_msg = f"Scrape cycle failed: {e}"
        logger.error(error_msg, exc_info=True)
        db.log_scrape("error", 0, str(e))
        if bot:
            try:
                await bot.send_message(
                    chat_id=target_chat_id,
                    text=f"❌ <b>Scrape Error</b>\n<code>{html.escape(str(e))}</code>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
        return error_msg


# ── Scheduled job callback ───────────────────────────────────────────

async def scheduled_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Called by the JobQueue on a repeating schedule."""
    logger.info("Scheduled check triggered.")
    await check_and_notify(context)


# ── Command handlers ─────────────────────────────────────────────────

@admin_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    product_count = db.get_product_count()
    last_scrape = db.get_last_scrape()

    msg = (
        "🏎️ <b>Fanatec Refurbished Monitor</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "✅ Bot is <b>active</b> and monitoring!\n\n"
        f"🔗 Target: <a href=\"{FANATEC_URL}\">Fanatec Refurbished</a>\n"
        f"⏱️ Check interval: every <b>{CHECK_INTERVAL_MINUTES}</b> minutes\n"
        f"📦 Products tracked: <b>{product_count}</b>\n"
    )

    if last_scrape:
        msg += f"🕐 Last check: <code>{last_scrape.get('timestamp', 'N/A')[:19]}</code>\n"

    # Show watchlist
    watchlist = db.get_watchlist()
    if watchlist:
        msg += f"\n🎯 Watchlist ({len(watchlist)} items):\n"
        for w in watchlist:
            msg += f"  • <code>{html.escape(w['keyword'])}</code>\n"

    msg += (
        "\n<b>Commands:</b>\n"
        "  /status — View all tracked products\n"
        "  /force_check — Trigger an immediate scan\n"
        "  /watch &lt;keyword&gt; — Add product to watchlist\n"
        "  /unwatch &lt;keyword&gt; — Remove from watchlist\n"
        "  /watchlist — View current watchlist\n"
        "  /help — Show this message\n"
    )

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@admin_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command."""
    products = db.get_all_products()
    last_scrape = db.get_last_scrape()
    msg = _format_status_message(products, last_scrape)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@admin_only
async def cmd_force_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /force_check command."""
    await update.message.reply_text("🔄 Running scan now…")
    summary = await check_and_notify(context, chat_id=update.effective_chat.id)
    await update.message.reply_text(summary)


@admin_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    await cmd_start(update, context)


@admin_only
async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /watch <keyword> — add a product keyword to the watchlist."""
    if not context.args:
        await update.message.reply_text(
            "Usage: /watch <keyword>\n\n"
            "Example: /watch formula v2.5\n"
            "The keyword is matched case-insensitively against product names.",
        )
        return

    keyword = " ".join(context.args)
    added = db.add_watch(keyword)
    if added:
        await update.message.reply_text(
            f"🎯 Added to watchlist: <code>{html.escape(keyword)}</code>\n\n"
            f"You'll get a 🚨 priority alert when a product matching "
            f"this keyword appears or becomes available.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(
            f"ℹ️ <code>{html.escape(keyword)}</code> is already on the watchlist.",
            parse_mode=ParseMode.HTML,
        )


@admin_only
async def cmd_unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /unwatch <keyword> — remove a keyword from the watchlist."""
    if not context.args:
        await update.message.reply_text("Usage: /unwatch <keyword>")
        return

    keyword = " ".join(context.args)
    removed = db.remove_watch(keyword)
    if removed:
        await update.message.reply_text(
            f"✅ Removed from watchlist: <code>{html.escape(keyword)}</code>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(
            f"❌ <code>{html.escape(keyword)}</code> was not found on the watchlist.",
            parse_mode=ParseMode.HTML,
        )


@admin_only
async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /watchlist — show the current watchlist."""
    watches = db.get_watchlist()
    if not watches:
        await update.message.reply_text(
            "📭 Watchlist is empty.\n\n"
            "Use /watch <keyword> to track a product.\n"
            "Example: /watch formula v2.5"
        )
        return

    msg = f"🎯 <b>Watchlist</b> ({len(watches)} items)\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for w in watches:
        keyword = html.escape(w['keyword'])
        added = w['added_at'][:10]  # date only
        msg += f"  • <code>{keyword}</code>  <i>(since {added})</i>\n"
    msg += (
        "\n━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "When a product matching any keyword appears\n"
        "or becomes available, you'll get a 🚨 priority alert.\n\n"
        "Manage: /watch &lt;keyword&gt; · /unwatch &lt;keyword&gt;"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


# ── Application startup ─────────────────────────────────────────────

async def post_init(application: Application) -> None:
    """Called after the Application has been initialized."""
    logger.info("Bot started. Setting up scheduled job...")

    # Seed default watchlist entry for ClubSport Formula V2.5X
    db.add_watch("formula v2.5")

    # Set up repeating job
    application.job_queue.run_repeating(
        scheduled_check,
        interval=CHECK_INTERVAL_MINUTES * 60,
        first=30,  # First check 30 seconds after startup
        name="fanatec_monitor",
    )

    # Build startup message with watchlist info
    watches = db.get_watchlist()
    watch_info = ""
    if watches:
        watch_items = ", ".join(f'"<code>{html.escape(w["keyword"])}</code>"' for w in watches)
        watch_info = f"\n🎯 Watchlist: {watch_items}"

    # Notify admin that bot started
    try:
        await application.bot.send_message(
            chat_id=TELEGRAM_ADMIN_USER_ID,
            text=(
                "🟢 <b>Fanatec Monitor Started!</b>\n\n"
                f"Checking every {CHECK_INTERVAL_MINUTES} minutes.\n"
                f"First scan in 30 seconds…{watch_info}"
            ),
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.warning(f"Could not send startup message: {e}")


def main() -> None:
    """Entry point: validate config, build bot, start polling."""
    if not validate_config():
        logger.critical("Configuration validation failed. Exiting.")
        raise SystemExit(1)

    logger.info("Building Telegram application...")

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Register command handlers
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("force_check", cmd_force_check))
    application.add_handler(CommandHandler("watch", cmd_watch))
    application.add_handler(CommandHandler("unwatch", cmd_unwatch))
    application.add_handler(CommandHandler("watchlist", cmd_watchlist))
    application.add_handler(CommandHandler("help", cmd_help))

    logger.info("Starting bot polling…")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
