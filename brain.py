import os
import re
from typing import Iterator

import anthropic
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

ANTHROPIC_MODELS = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-5",
}
DEFAULT_MODEL = os.environ.get("ACTIVE_MODEL", "haiku").lower()

_ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
if not _ollama_host.endswith("/v1"):
    _ollama_host += "/v1"

_anthropic_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
_ollama_client = OpenAI(base_url=_ollama_host, api_key="ollama")

SYSTEM_PROMPT = """You are a personal operating system assistant. You help the user manage their projects, goals, and weekly execution.

You have access to their project context (memory files) and can read/update them.

Your job:
- Help them figure out what to do next
- Absorb vague thoughts/goals and turn them into concrete next actions
- Update context files when they log progress or new goals
- Be direct and low-friction — they want to execute, not plan

When you want to update a context file, output a block like this at the END of your response:
<update_context project="project-name">
Updated context content here. Keep it concise — running summary of goals, progress, next actions.
</update_context>

For global context (cross-project notes):
<update_context project="_global">
Content here.
</update_context>

Keep context files tight. Summarize, don't append forever.

For updating non-context files (roadmap, backlog, todo lists):
<update_file project="project-name" file="filename.md">
Full file content here
</update_file>

Use update_file for task lists, roadmaps, and any structured content the user edits directly.
Use update_context for running memory/summaries only.
Always show the user what you're proposing and obtain approval before writing it.

Write your conversational replies in plain text only — no markdown formatting (no **bold**, no # headers, no markdown bullet lists). These are read in plain-text interfaces (a terminal and Telegram) that don't render markdown, so it just shows up as literal asterisks and clutter."""

BRAINDUMP_PROMPT = """You are helping the user process a "brain dump" — a raw, unstructured stream of everything currently on their mind. You'll receive the full vault context (all projects and their current state) followed by the dump text.

For each distinct thought or item in the dump, decide which existing project it belongs to. If nothing fits, file it under "the-lab" (the general backlog/catch-all project). Group items by project, and for each project touched, emit exactly one block:

<update_file project="project-name" file="notes.md">
* [ ] item text
* [ ] another item for this same project
</update_file>

Format every item as a checkbox line (`* [ ] ...`), one per line, inside the block for its assigned project. Keep each item short and concrete — rephrase rambling thoughts into a clear actionable line where reasonable, but don't invent detail that wasn't there.

After all the filing blocks, write 2-4 sentences recommending ONE project as this week's focus, considering the current active focus, any deferred/shelved projects, and everything you just filed. Be direct — this is a recommendation, not a question. Write this reasoning in plain text only — no markdown formatting (no **bold**, no # headers) — it's read in Telegram, which shows literal asterisks rather than rendering them. End your response with exactly one final line in this exact format:
RECOMMENDED_FOCUS: project-name"""

FOCUS_NEGOTIATION_PROMPT = """You're continuing a conversation about what the user's focus should be this week. Their brain dump has already been filed into the vault — don't file anything again, just discuss the focus decision using the conversation so far and the vault context provided.

Respond conversationally to what they just said, in plain text only — no markdown formatting (no **bold**, no # headers) — it's read in Telegram, which shows literal asterisks rather than rendering them. Then end your response with exactly one final line in this exact format:
RECOMMENDED_FOCUS: project-name"""


def think(messages: list[dict], model: str | None = None, system: str = SYSTEM_PROMPT) -> str:
    model = model or DEFAULT_MODEL

    if model == "llama":
        try:
            response = _ollama_client.chat.completions.create(
                model="llama3.2",
                messages=[{"role": "system", "content": system}] + messages,
                max_tokens=4096,
            )
            return response.choices[0].message.content or ""
        except Exception:
            model = "haiku"

    response = _anthropic_client.messages.create(
        model=ANTHROPIC_MODELS[model],
        max_tokens=4096,
        system=system,
        messages=messages,
    )
    return next((b.text for b in response.content if b.type == "text"), "")


def think_stream(messages: list[dict], model: str | None = None, system: str = SYSTEM_PROMPT) -> Iterator[str]:
    model = model or DEFAULT_MODEL

    if model == "llama":
        try:
            stream = _ollama_client.chat.completions.create(
                model="llama3.2",
                messages=[{"role": "system", "content": system}] + messages,
                max_tokens=4096,
                stream=True,
            )
        except Exception:
            model = "haiku"
        else:
            for chunk in stream:
                text = chunk.choices[0].delta.content or ""
                if text:
                    yield text
            return

    with _anthropic_client.messages.stream(
        model=ANTHROPIC_MODELS[model],
        max_tokens=4096,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text


def parse_updates(response_text: str) -> tuple[str, list[tuple[str, str]], list[tuple[str, str, str]]]:
    ctx_pattern = r'<update_context project="([^"]+)">(.*?)</update_context>'
    context_updates = [(project, content.strip()) for project, content in re.findall(ctx_pattern, response_text, re.DOTALL)]
    clean = re.sub(ctx_pattern, '', response_text, flags=re.DOTALL).strip()

    file_pattern = r'<update_file project="([^"]+)" file="([^"]+)">(.*?)</update_file>'
    file_updates = [(project, filename, content.strip()) for project, filename, content in re.findall(file_pattern, clean, flags=re.DOTALL)]
    clean = re.sub(file_pattern, '', clean, flags=re.DOTALL).strip()

    return clean, context_updates, file_updates


def parse_recommended_focus(text: str) -> str | None:
    match = re.search(r'^RECOMMENDED_FOCUS:\s*(\S+)\s*$', text, re.MULTILINE)
    return match.group(1) if match else None
