import os
import json
import logging
import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Update, Bot
from telegram.ext import Application

from bot import JobBot, SEEN_FILE, SITES_FILE, load_json, save_json

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def scheduled_scan(job_bot: JobBot):
    if job_bot.is_scanning:
        logger.info("Scheduled scan skipped - manual scan in progress")
        return

    logger.info("Starting scheduled scan...")
    job_bot.is_scanning = True

    try:
        new_jobs = job_bot.scraper.run_scan(job_bot.seen_ids)

        for job in new_jobs:
            text = job_bot.scraper.format_job(job)
            await job_bot.send_message(text)
            job_bot.seen_ids.add(job["id"])
            await asyncio.sleep(0.5)

        job_bot.save_seen()
        logger.info(f"Scheduled scan complete: {len(new_jobs)} new jobs sent")

        stats = job_bot.scraper.last_stats
        stats["run_type"] = "scheduled"
    except Exception as e:
        logger.error(f"Scheduled scan error: {e}")
        try:
            await job_bot.send_message(f"⚠️ Scheduled scan failed: {e}")
        except Exception:
            pass
    finally:
        job_bot.is_scanning = False


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        return

    job_bot = JobBot()
    app = job_bot.build_app()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scheduled_scan,
        CronTrigger(hour="*/12", minute=0),
        args=[job_bot],
        id="job_scan",
        name="Workday Job Scan",
    )

    async def post_init(application: Application):
        scheduler.start()
        logger.info("Scheduler started - will run every 12 hours")

        await application.bot.set_my_commands([
            ("start", "Start the bot"),
            ("help", "Show available commands"),
            ("check", "Force scan now"),
            ("sites", "List configured companies"),
            ("addsite", "Add a new Workday company"),
            ("rmsite", "Remove a company"),
            ("status", "Last run info"),
            ("seen", "Recently sent jobs"),
        ])

        logger.info("Bot started successfully")

    app.post_init = post_init

    logger.info("Starting bot polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
