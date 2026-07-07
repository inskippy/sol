import asyncio
import os
import re

from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

import brain
import state
import vault

load_dotenv()

_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

_AFFIRMATIVE = {"yes", "y", "confirm", "sounds good", "do it", "yeah", "yep"}

_pending_file_confirmation: tuple[str, str, str] | None = None
_focus_negotiation: dict | None = None


def send_nudge(message: str) -> None:
    if not _BOT_TOKEN or not _CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env")

    async def _send():
        bot = Bot(token=_BOT_TOKEN)
        async with bot:
            await bot.send_message(chat_id=_CHAT_ID, text=message)

    asyncio.run(_send())


def _strip_recommended_focus(text: str) -> str:
    return re.sub(r'^RECOMMENDED_FOCUS:.*$', '', text, flags=re.MULTILINE).strip()


def _handle_model_command(text: str) -> str:
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return f"Usage: /model <name> — valid options: {', '.join(sorted(state.VALID_MODELS))}"

    model_name = parts[1].strip().lower()
    current_state = state.load_state()
    try:
        state.set_model(model_name, current_state)
    except ValueError as e:
        return str(e)
    state.save_state(current_state)
    return f"Model set to {model_name}."


def _handle_braindump_command(text: str) -> str:
    global _focus_negotiation

    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return "Usage: /braindump <everything on your mind>"
    dump_text = parts[1].strip()

    context_block = vault.build_context_block(None)
    prompt = f"{context_block}\n---\nBrain dump: {dump_text}"
    history = [{"role": "user", "content": prompt}]
    raw = brain.think(history, model="sonnet", system=brain.BRAINDUMP_PROMPT)
    clean, _, file_updates = brain.parse_updates(raw)

    filed_summary = []
    todo_items = []
    for project, filename, content in file_updates:
        vault.append_file(project, filename, content)
        filed_summary.append(f"{project}/{filename}")
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("* [ ]"):
                todo_items.append((project, line[len("* [ ]"):].strip()))

    if todo_items:
        vault.append_global_todo(todo_items)

    recommended = brain.parse_recommended_focus(clean)
    history.append({"role": "assistant", "content": raw})
    _focus_negotiation = {"history": history, "recommended": recommended}

    reasoning = _strip_recommended_focus(clean)
    summary = f"Filed {len(todo_items)} item(s): {', '.join(filed_summary)}" if filed_summary else "Nothing to file."
    focus_prompt = f"\n\nReply 'yes' to make {recommended} the focus, or name a different project." if recommended else ""
    return f"{summary}\n\n{reasoning}{focus_prompt}"


def _resolve_focus_negotiation(text: str) -> str:
    global _focus_negotiation
    negotiation = _focus_negotiation
    text_lower = text.strip().lower()

    resolved_project = next((p for p in vault.list_projects() if p.lower() == text_lower), None)
    if resolved_project is None and text_lower in _AFFIRMATIVE:
        resolved_project = negotiation["recommended"]

    if resolved_project:
        current_state = state.load_state()
        state.set_focus(resolved_project, current_state)
        state.save_state(current_state)
        _focus_negotiation = None
        return f"Focus set to {resolved_project}."

    negotiation["history"].append({"role": "user", "content": text})
    raw = brain.think(negotiation["history"], model="sonnet", system=brain.FOCUS_NEGOTIATION_PROMPT)
    negotiation["history"].append({"role": "assistant", "content": raw})
    clean, _, _ = brain.parse_updates(raw)
    negotiation["recommended"] = brain.parse_recommended_focus(clean) or negotiation["recommended"]

    reasoning = _strip_recommended_focus(clean)
    focus_prompt = f"\n\nReply 'yes' to make {negotiation['recommended']} the focus, or name a different project." if negotiation["recommended"] else ""
    return f"{reasoning}{focus_prompt}"


def _resolve_file_confirmation(text: str) -> str:
    global _pending_file_confirmation
    project, filename, content = _pending_file_confirmation
    _pending_file_confirmation = None

    if text.strip().lower() in ("y", "yes"):
        vault.write_file(project, filename, content)
        return f"Applied update to {project}/{filename}."
    return "Skipped."


def _handle_chat(text: str) -> str:
    global _pending_file_confirmation
    current_state = state.load_state()
    active_project = current_state.get("active_focus")
    model = current_state.get("active_model")

    context_block = vault.build_context_block(active_project)
    augmented = f"{context_block}\n---\nUser message: {text}"
    raw = brain.think([{"role": "user", "content": augmented}], model=model)
    clean, context_updates, file_updates = brain.parse_updates(raw)

    notes = []
    for project, content in context_updates:
        vault.write_context(project, content)
        notes.append(f"(updated {project}/_context.md)")

    reply = f"{clean}\n\n{' '.join(notes)}".strip() if notes else clean

    if file_updates:
        project, filename, content = file_updates[0]
        diff = vault.preview_file_write(project, filename, content)
        _pending_file_confirmation = (project, filename, content)
        preview = content if diff == "(new file)" else diff
        reply += f"\n\nSOL wants to update {project}/{filename}:\n{preview}\n\nApply? [y/n]"

    return reply


def _route_message(text: str) -> str:
    if _pending_file_confirmation is not None:
        return _resolve_file_confirmation(text)
    if _focus_negotiation is not None:
        return _resolve_focus_negotiation(text)
    if text.lower().startswith("/model"):
        return _handle_model_command(text)
    if text.lower().startswith("/braindump"):
        return _handle_braindump_command(text)
    return _handle_chat(text)


async def _handle_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if str(update.message.chat_id) != _CHAT_ID:
        return
    text = (update.message.text or "").strip()
    if not text:
        return
    reply = await asyncio.to_thread(_route_message, text)
    await update.message.reply_text(reply)


def listen() -> None:
    if not _BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN must be set in .env")
    app = Application.builder().token(_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, _handle_update))
    app.run_polling()
