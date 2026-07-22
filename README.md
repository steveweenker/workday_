# Workday Job Scraper Bot

Telegram bot that scans Workday career sites for entry-level Software Engineer roles in India and sends new postings to your Telegram.

## Deploy to Railway

1. Push this folder to a GitHub repo
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Add these environment variables in Railway dashboard:
   - `TELEGRAM_BOT_TOKEN` = your bot token
   - `TELEGRAM_CHAT_ID` = your chat ID
4. Railway will auto-deploy

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/help` | List all commands |
| `/check` | Force scan now |
| `/sites` | List configured companies |
| `/addsite <name> <slug> <subdomain> <path> [url]` | Add a company |
| `/rmsite <name>` | Remove a company |
| `/status` | Last scan stats |
| `/seen` | Recently sent jobs |

## Adding a Workday Company

```
/addsite Cisco cisco wd1 cisco https://www.cisco.com
```

The URL format is: `https://{slug}.{subdomain}.myworkdayjobs.com/en-US/{site_path}`

## Files

- `main.py` - Entry point (bot + scheduler)
- `bot.py` - Telegram bot commands
- `scraper.py` - Workday API scraping logic
- `sites.json` - Company configurations
- `requirements.txt` - Python dependencies
- `Procfile` - Railway process definition
- `railway.json` - Railway config
