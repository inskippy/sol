import asyncio
import os

from dotenv import load_dotenv
from telegram import Bot

load_dotenv()

_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def send_nudge(message: str) -> None:
    if not _BOT_TOKEN or not _CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env")

    async def _send():
        bot = Bot(token=_BOT_TOKEN)
        async with bot:
            await bot.send_message(chat_id=_CHAT_ID, text=message)

    asyncio.run(_send())
