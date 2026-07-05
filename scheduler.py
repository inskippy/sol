import os

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

import brain
import state
import telegram_bot
import vault

load_dotenv()

NUDGE_DAY = os.environ.get("NUDGE_DAY", "monday").lower()[:3]
NUDGE_HOUR, NUDGE_MINUTE = os.environ.get("NUDGE_TIME", "08:00").split(":")
TZ = os.environ.get("TZ", "UTC")


def weekly_nudge() -> None:
    context = vault.read_all_contexts()
    prompt = (
        f"{context}\n---\n"
        "Generate this week's focus nudge in 2-4 sentences: what's the active "
        "project's focus, and anything queued that's worth mentioning."
    )
    raw = brain.think([{"role": "user", "content": prompt}], model="haiku")
    clean, _, _ = brain.parse_updates(raw)
    telegram_bot.send_nudge(clean)


def check_drift_job() -> None:
    current_state = state.load_state()
    messages = state.check_drift(current_state)
    if messages:
        state.save_state(current_state)
        for message in messages:
            telegram_bot.send_nudge(message)


def intake_absorb() -> None:
    pass  # Phase 3 — absorb notes.md intake logs into structured tasks


def main() -> None:
    scheduler = BlockingScheduler(timezone=TZ)
    trigger = CronTrigger(day_of_week=NUDGE_DAY, hour=NUDGE_HOUR, minute=NUDGE_MINUTE)
    scheduler.add_job(weekly_nudge, trigger)
    scheduler.add_job(check_drift_job, trigger)
    scheduler.start()


if __name__ == "__main__":
    main()
