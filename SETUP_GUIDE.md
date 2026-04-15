# Fanatec Stock Searcher — Setup & Deployment Guide

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Get Your Telegram Bot Token](#1-get-your-telegram-bot-token)
3. [Find Your Telegram User ID](#2-find-your-telegram-user-id)
4. [Local Setup & Testing](#3-local-setup--testing)
5. [Deployment Options](#4-deployment-options)
   - [Option A: PythonAnywhere (Recommended)](#option-a-pythonanywhere-recommended-free)
   - [Option B: Render.com](#option-b-rendercom-free-with-caveats)
   - [Option C: Oracle Cloud Always Free](#option-c-oracle-cloud-always-free-best-for-247)
6. [Handling Ephemeral Filesystems](#5-handling-ephemeral-filesystems)
7. [Troubleshooting](#6-troubleshooting)

---

## Prerequisites

- Python 3.10 or higher
- A Telegram account
- Git (for deployment)

---

## 1. Get Your Telegram Bot Token

1. Open Telegram and search for **@BotFather**.
2. Start a chat and send: `/newbot`
3. Follow the prompts:
   - **Name**: `Fanatec Stock Searcher` (display name)
   - **Username**: `fanatec_stock_bot` (must end with `bot`, must be unique)
4. BotFather will reply with your **HTTP API Token**, which looks like:
   ```
   7123456789:AAH1234567890abcdefghijklmnopqrstuv
   ```
5. Copy this token — it goes in your `.env` file as `TELEGRAM_BOT_TOKEN`.

> **Optional but recommended**: Also send these commands to BotFather:
> - `/setdescription` — Add a description for your bot
> - `/setabouttext` — Set the "About" text
> - `/setcommands` — Register the commands:
>   ```
>   start - Start the bot and see status
>   status - View all tracked products
>   force_check - Trigger an immediate scan
>   help - Show help message
>   ```

---

## 2. Find Your Telegram User ID

Your **numeric User ID** is needed so only YOU can control the bot.

### Method 1: @userinfobot
1. Search for **@userinfobot** in Telegram.
2. Send it any message.
3. It will reply with your User ID (a number like `123456789`).

### Method 2: @RawDataBot
1. Search for **@RawDataBot** in Telegram.
2. Send it any message.
3. Look for `"id":` in the JSON response — that's your User ID.

Copy this number into your `.env` file as `TELEGRAM_ADMIN_USER_ID`.

---

## 3. Local Setup & Testing

### Step 1: Clone the project
```bash
git clone https://github.com/sa1ntsinner/Fanatec_Stock_searcher.git
cd Fanatec_Stock_searcher
```

### Step 2: Create a virtual environment
```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux
```

### Step 3: Install dependencies
```bash
pip install -r requirements.txt
```

### Step 4: Install Playwright browsers (for the fallback scraper)
```bash
playwright install chromium
```
> **Note**: This downloads a Chromium binary (~250MB). If you want to test with `cloudscraper` only, you can skip this and set `USE_PLAYWRIGHT_ONLY=false`.

### Step 5: Configure environment variables
```bash
copy .env.example .env
# Then edit .env with your TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_USER_ID
```

### Step 6: Run the bot
```bash
python bot.py
```

You should see log output confirming the bot has started. Open Telegram and send `/start` to your bot!

---

## 4. Deployment Options

### Option A: PythonAnywhere (Recommended, Free)

**Pros**: Persistent filesystem (SQLite survives restarts), easy setup.  
**Cons**: Free tier limits: 1 scheduled task/day, limited outbound internet (whitelist-only for free accounts), CPU throttling.

> ⚠️ **Important**: PythonAnywhere free tier only allows HTTP(S) requests to sites on their [whitelist](https://www.pythonanywhere.com/whitelist/). Fanatec.com may or may not be listed. If it's not, you'll need a paid plan ($5/month) — which is still cheap and gives you always-on tasks.

#### Steps:

1. **Create an account** at [pythonanywhere.com](https://www.pythonanywhere.com)

2. **Upload your files**:
   - Go to **Files** tab → Upload `bot.py`, `scraper.py`, `database.py`, `config.py`, `requirements.txt`
   - Or use Git:
     ```bash
     git clone https://github.com/sa1ntsinner/Fanatec_Stock_searcher.git
     ```

3. **Open a Bash console** and install dependencies:
   ```bash
   pip3 install --user -r requirements.txt
   playwright install chromium  # If using Playwright
   ```

4. **Create your .env file**:
   ```bash
   cp .env.example .env
   nano .env   # Edit with your real values
   ```

5. **For always-on execution** (Paid plan, $5/month):
   - Go to **Web** tab → **Always-on tasks**
   - Add command: `python3 /home/YOUR_USERNAME/Fanatec_Stock_searcher/bot.py`

6. **For free tier** (Scheduled task, limited):
   - Go to **Tasks** tab → Add a daily scheduled task:
     ```
     python3 /home/YOUR_USERNAME/Fanatec_Stock_searcher/bot.py
     ```
   - The bot will run until PythonAnywhere kills it (free tier has CPU limits).

---

### Option B: Render.com (Free with Caveats)

**Pros**: Easy Git-based deploys, Docker support.  
**Cons**: Free web services spin down after 15 min inactivity. **Ephemeral filesystem** — your SQLite DB resets on every deploy.

#### Steps:

1. **Push your code to GitHub/GitLab**.

2. **Create a `render.yaml`** (Infrastructure as Code):
   ```yaml
   services:
     - type: web
       name: fanatec-monitor
       runtime: python
       plan: free
       buildCommand: |
         pip install -r requirements.txt
         playwright install chromium
         playwright install-deps
       startCommand: python bot.py
       envVars:
         - key: TELEGRAM_BOT_TOKEN
           sync: false
         - key: TELEGRAM_ADMIN_USER_ID
           sync: false
         - key: PYTHON_VERSION
           value: 3.11.6
   ```

3. **Go to [render.com](https://render.com)** → New → Web Service → Connect your repo.

4. **Set environment variables** in the Render dashboard:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_ADMIN_USER_ID`

5. **Keep-alive workaround** (to prevent 15-min spin-down):
   - Sign up for [UptimeRobot](https://uptimerobot.com) (free)
   - Add a monitor pointing to your Render service URL every 5 minutes
   - This sends periodic HTTP requests that keep the service awake

> ⚠️ **Database Warning**: On Render free tier, the filesystem is ephemeral. Every time your service restarts (deploys, crashes, or is woken up), the SQLite database is **wiped**. See [Section 5](#5-handling-ephemeral-filesystems) for solutions.

---

### Option C: Oracle Cloud Always Free (Best for 24/7)

**Pros**: Full VPS, persistent disk, truly free forever, most reliable.  
**Cons**: Requires Linux server management, more complex setup.

#### Steps:

1. **Create a free Oracle Cloud account** at [cloud.oracle.com](https://cloud.oracle.com)
   - You get 2 AMD x86 instances or 4 ARM Ampere cores (24GB RAM!) for free.

2. **Create a compute instance**:
   - Shape: `VM.Standard.A1.Flex` (ARM) or `VM.Standard.E2.1.Micro` (x86)
   - OS: Ubuntu 22.04 or later
   - Add your SSH key

3. **SSH into your instance** and set up:
   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo apt install python3 python3-pip python3-venv git -y
   
   # Clone your repo
   git clone https://github.com/sa1ntsinner/Fanatec_Stock_searcher.git
   cd Fanatec_Stock_searcher
   
   # Create venv and install
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   playwright install chromium
   playwright install-deps
   
   # Configure
   cp .env.example .env
   nano .env
   ```

4. **Create a systemd service** for auto-start:
   ```bash
   sudo nano /etc/systemd/system/fanatec-bot.service
   ```
   Contents:
   ```ini
   [Unit]
   Description=Fanatec Stock Searcher Bot
   After=network.target
   
   [Service]
   Type=simple
   User=ubuntu
   WorkingDirectory=/home/ubuntu/Fanatec_Stock_searcher
   ExecStart=/home/ubuntu/Fanatec_Stock_searcher/venv/bin/python bot.py
   Restart=always
   RestartSec=10
   Environment=PYTHONUNBUFFERED=1
   
   [Install]
   WantedBy=multi-user.target
   ```

5. **Enable and start the service**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable fanatec-bot
   sudo systemctl start fanatec-bot
   
   # Check status
   sudo systemctl status fanatec-bot
   
   # View logs
   sudo journalctl -u fanatec-bot -f
   ```

---

## 5. Handling Ephemeral Filesystems

On platforms like **Render.com**, the SQLite database file is lost on every restart. Here are your options:

### Option 1: Accept the Reset (Simplest)
- After each restart, the bot treats all products as "new" and sends alerts again.
- Fine if restarts are rare and you don't mind duplicate "new product" alerts.

### Option 2: Use MongoDB Atlas Free Tier
- **512MB free forever**, cloud-hosted, no filesystem dependency.

1. Create an account at [mongodb.com/atlas](https://www.mongodb.com/atlas)
2. Create a free M0 cluster
3. Get your connection string
4. Replace the SQLite `database.py` with a MongoDB version using `pymongo`
5. Set `MONGODB_URI` in your environment variables

> This is the recommended approach for Render.com deployments.

### Option 3: Use PythonAnywhere or Oracle Cloud
- Both have **persistent filesystems** — SQLite works perfectly and survives restarts.

---

## 6. Troubleshooting

### Bot doesn't respond to commands
- Verify `TELEGRAM_BOT_TOKEN` is correct (try `https://api.telegram.org/bot<TOKEN>/getMe`)
- Verify `TELEGRAM_ADMIN_USER_ID` matches YOUR user ID
- Check logs for error messages

### Scraper returns 0 products
- Fanatec may have changed their HTML structure → check the page manually
- Cloudflare may be blocking → try setting `USE_PLAYWRIGHT_ONLY=true`
- Try running `playwright install chromium` if you haven't
- Check your internet connection and any firewall/proxy settings

### "cloudscraper not working"
- Modern Cloudflare often blocks cloudscraper → Set `USE_PLAYWRIGHT_ONLY=true`
- The bot will automatically fall back to Playwright if cloudscraper fails

### Rate limiting from Telegram
- The bot has built-in 0.5s delays between alert messages
- If you still hit limits, increase `CHECK_INTERVAL_MINUTES`

### Database errors
- Delete `products.db` and restart — a fresh database will be created
- Ensure the bot has write permissions to its directory

### Playwright won't install
- On Linux: `playwright install-deps` (installs system dependencies)
- On Render.com: Add `playwright install-deps` to the build command
- On PythonAnywhere: Playwright may not work on free tier (use cloudscraper only)
