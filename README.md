# 🏎️ Fanatec Stock Monitor

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Telegram Bot](https://img.embedded.org/api/badge/telegram-bot.svg?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/BotFather)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

> **Real-time stock monitoring for the Fanatec Certified Refurbished inventory.** Never miss out on high-demand racing gear again.

---

## ✨ Features

- 🕵️ **Automatic Scraper**: Periodically monitors the Fanatec Certified Refurbished page.
- 🚨 **Priority Watchlist**: Instant alerts for your most-wanted products (e.g., ClubSport Formula V2.5X).
- 🤫 **Silent Stealth Mode**: Runs fully hidden in the background on Windows.
- 📦 **Database Persistence**: Tracks price changes and product availability history.
- 📱 **Telegram Integration**: Direct notifications to your phone with quick links.

---

## 🛠️ Tech Stack

- **Core**: Python 3.x
- **Bot Engine**: [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
- **Scraping**: Cloudscraper & BeautifulSoup4 (with Playwright fallback)
- **Database**: SQLite3
- **Automation**: Windows VBScript & PowerShell Integration

---

## 🚀 Quick Start

### 1. Requirements
Ensure you have Python 3.10 or higher installed.

```bash
pip install -r requirements.txt
```

### 2. Configuration
Create a `.env` file in the root directory (see `.env.example`):
```env
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_ADMIN_USER_ID=your_id_here
CHECK_INTERVAL_MINUTES=5
```

### 3. Launch
The bot is designed to run seamlessly on Windows:
- Double-click **Fanatec Monitor** on your desktop.
- It will automatically launch on every PC startup in hidden mode.

---

## 📂 Project Structure

- `bot.py`: Main Telegram bot logic and command handlers.
- `scraper.py`: Advanced scraping engine with anti-bot bypass.
- `database.py`: Product tracking and watchlist management.
- `start_bot.bat`: Background process launcher.
- `launch_hidden.vbs`: Silent windowless execution wrapper.

---

## ⚖️ License

Distributed under the MIT License. See `LICENSE` for more information.

---

<p align="center">
  Made for sim racers 🏎️
</p>
