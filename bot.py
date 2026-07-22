import os
import json
import logging
import asyncio
from datetime import datetime
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from scraper import JobScraper

logger = logging.getLogger(__name__)

SEEN_FILE = "seen_jobs.json"
SITES_FILE = "sites.json"


def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else {}


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class JobBot:
    def __init__(self):
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        self.sites_config = load_json(SITES_FILE, {"sites": [], "search_queries": ["Software Engineer"]})
        self.seen_data = load_json(SEEN_FILE, {"sent_ids": []})
        self.seen_ids = set(self.seen_data.get("sent_ids", []))
        self.scraper = JobScraper(self.sites_config)
        self.is_scanning = False

    def save_seen(self):
        self.seen_data["sent_ids"] = list(self.seen_ids)
        save_json(SEEN_FILE, self.seen_data)

    async def send_message(self, text, parse_mode="HTML"):
        from telegram import Bot
        bot = Bot(token=self.token)
        await bot.send_message(
            chat_id=self.chat_id,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 <b>Workday Job Bot</b>\n\n"
            "I scan Workday career sites for entry-level Software Engineer roles in India "
            "and send new postings to your Telegram.\n\n"
            "Type /help to see all commands.",
            parse_mode="HTML",
        )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "📋 <b>Available Commands</b>\n\n"
            "/check - Force scan now\n"
            "/sites - List configured companies\n"
            "/addsite &lt;slug&gt; &lt;subdomain&gt; &lt;path&gt; &lt;url&gt; - Add company\n"
            "/rmsite &lt;name&gt; - Remove company\n"
            "/status - Last run info\n"
            "/seen - Recently sent jobs\n"
            "/help - This message",
            parse_mode="HTML",
        )

    async def cmd_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.is_scanning:
            await update.message.reply_text("⏳ Scan already in progress...")
            return

        self.is_scanning = True
        msg = await update.message.reply_text("🔍 Scanning all Workday sites...")

        try:
            new_jobs = self.scraper.run_scan(self.seen_ids)

            for job in new_jobs:
                text = self.scraper.format_job(job)
                await self.send_message(text)
                self.seen_ids.add(job["id"])
                await asyncio.sleep(0.5)

            self.save_seen()

            if new_jobs:
                await msg.edit_text(f"✅ Done! Found and sent {len(new_jobs)} new jobs.")
            else:
                await msg.edit_text("✅ Done! No new matching jobs found.")

            self.scraper.last_stats["run_type"] = "manual"
        except Exception as e:
            logger.error(f"Scan error: {e}")
            await msg.edit_text(f"❌ Error during scan: {e}")
        finally:
            self.is_scanning = False

    async def cmd_sites(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        sites = self.sites_config.get("sites", [])
        if not sites:
            await update.message.reply_text("No sites configured.")
            return

        lines = ["🏢 <b>Configured Companies</b>\n"]
        for i, s in enumerate(sites, 1):
            url = f"https://{s['slug']}.{s['subdomain']}.myworkdayjobs.com/en-US/{s['site_path']}"
            lines.append(f"{i}. <b>{s['name']}</b>")
            lines.append(f"   {url}\n")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def cmd_addsite(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args
        if len(args) < 4:
            await update.message.reply_text(
                "Usage: /addsite &lt;name&gt; &lt;slug&gt; &lt;subdomain&gt; &lt;site_path&gt; [career_url]\n\n"
                "Example: /addsite Cisco cisco wd1 cisco https://www.cisco.com",
                parse_mode="HTML",
            )
            return

        name, slug, subdomain, site_path = args[0], args[1], args[2], args[3]
        career_url = args[4] if len(args) > 4 else f"https://{slug}.{subdomain}.myworkdayjobs.com"

        new_site = {
            "name": name,
            "slug": slug,
            "subdomain": subdomain,
            "site_path": site_path,
            "career_url": career_url,
        }

        self.sites_config["sites"].append(new_site)
        save_json(SITES_FILE, self.sites_config)

        await update.message.reply_text(
            f"✅ Added <b>{name}</b>\n"
            f"https://{slug}.{subdomain}.myworkdayjobs.com/en-US/{site_path}",
            parse_mode="HTML",
        )

    async def cmd_rmsite(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args
        if not args:
            await update.message.reply_text("Usage: /rmsite &lt;company_name&gt;")
            return

        name = " ".join(args)
        sites = self.sites_config.get("sites", [])
        found = False

        for i, s in enumerate(sites):
            if s["name"].lower() == name.lower():
                removed = sites.pop(i)
                save_json(SITES_FILE, self.sites_config)
                await update.message.reply_text(f"✅ Removed <b>{removed['name']}</b>", parse_mode="HTML")
                found = True
                break

        if not found:
            await update.message.reply_text(f"❌ Company '{name}' not found. Use /sites to see all.")

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        stats = self.scraper.last_stats
        last_run = self.scraper.last_run

        if not stats:
            await update.message.reply_text("No scans have been run yet. Use /check to start.")
            return

        lines = [
            "📊 <b>Last Scan Status</b>\n",
            f"🕐 Last run: {last_run or 'Never'}",
            f"🏢 Sites checked: {stats.get('sites_checked', 0)}",
            f"📄 Total jobs found: {stats.get('total_jobs', 0)}",
            f"🎯 Matching India SE jobs: {stats.get('matching_jobs', 0)}",
            f"🆕 New jobs sent: {stats.get('new_jobs', 0)}",
            f"📨 Total jobs sent (all time): {len(self.seen_ids)}",
            "",
            "<b>Per-site breakdown:</b>",
        ]

        for name, detail in stats.get("site_details", {}).items():
            if "error" in detail:
                lines.append(f"  ❌ {name}: {detail['error']}")
            else:
                lines.append(f"  ✅ {name}: {detail['total']} total, {detail['matching']} matching")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def cmd_seen(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.seen_ids:
            await update.message.reply_text("No jobs have been sent yet.")
            return

        lines = ["📨 <b>Recently Sent Jobs</b>\n"]
        for jid in list(self.seen_ids)[-20:]:
            parts = jid.split("|", 1)
            company = parts[0] if len(parts) > 1 else "?"
            job_path = parts[1] if len(parts) > 1 else jid
            job_name = job_path.split("/")[-1].replace("_", " ") if "/" in job_path else job_path
            lines.append(f"• [{company}] {job_name}")

        if len(self.seen_ids) > 20:
            lines.append(f"\n... and {len(self.seen_ids) - 20} more")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "I don't understand that. Type /help to see available commands."
        )

    def build_app(self):
        app = Application.builder().token(self.token).build()

        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CommandHandler("check", self.cmd_check))
        app.add_handler(CommandHandler("sites", self.cmd_sites))
        app.add_handler(CommandHandler("addsite", self.cmd_addsite))
        app.add_handler(CommandHandler("rmsite", self.cmd_rmsite))
        app.add_handler(CommandHandler("status", self.cmd_status))
        app.add_handler(CommandHandler("seen", self.cmd_seen))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

        return app
