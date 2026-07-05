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
Always show the user what you're proposing and obtain approval before writing it."""


def think(messages: list[dict], model: str | None = None, system: str = SYSTEM_PROMPT) -> str:
    model = model or DEFAULT_MODEL

    if model == "llama":
        try:
            response = _ollama_client.chat.completions.create(
                model="llama3.2",
                messages=[{"role": "system", "content": system}] + messages,
                max_tokens=1500,
            )
            return response.choices[0].message.content or ""
        except Exception:
            model = "haiku"

    response = _anthropic_client.messages.create(
        model=ANTHROPIC_MODELS[model],
        max_tokens=1500,
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
                max_tokens=1500,
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
        max_tokens=1500,
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
