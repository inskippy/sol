import os
import sys
import anthropic
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
VAULT_PATH = Path(os.environ.get("VAULT_PATH"))
PROJECTS_PATH = VAULT_PATH / "projects"
GLOBAL_CONTEXT = VAULT_PATH / "_global_context.md"

ACTIVE_MODEL = str(os.environ.get("ACTIVE_MODEL")).lower() # claude or llama3.2
match ACTIVE_MODEL:
    case "claude":
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    case "llama3.2":
        client = OpenAI(
            base_url="http://localhost:11434/v1",
            api_key="ollama"  # required by library, value ignored
        )
    case _:
        raise Exception("Environment variable (.env file) ACTIVE_MODEL is missing.")

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

def read_context(project_name: str) -> str:
    if project_name == "_global":
        path = GLOBAL_CONTEXT
    else:
        path = PROJECTS_PATH / project_name / "_context.md"
    
    if path.exists():
        content = path.read_text().strip()
        return content if content else "(empty)"
    return "(no context file found)"

def write_context(project_name: str, content: str):
    if project_name == "_global":
        path = GLOBAL_CONTEXT
    else:
        path = PROJECTS_PATH / project_name / "_context.md"
    
    if not str(path).startswith(str(VAULT_PATH.resolve())):
        print(f"  ⚠ blocked write outside vault: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    path.write_text(f"*Last updated: {timestamp}*\n\n{content}")
    print(f"  ↳ updated {path.relative_to(VAULT_PATH)}")

def write_file(project_name: str, filename: str, content: str):
    path = PROJECTS_PATH / project_name / filename
    path = path.resolve()
    if not str(path).startswith(str(VAULT_PATH.resolve())):
        print(f"  ⚠ blocked write outside vault: {path}")
        return
    path.write_text(content)
    print(f"  ↳ updated {path.relative_to(VAULT_PATH)}")

def list_projects() -> list[str]:
    if not PROJECTS_PATH.exists():
        return []
    return [p.name for p in PROJECTS_PATH.iterdir() if p.is_dir()]

def build_context_block(active_project: str | None) -> str:
    projects = list_projects()
    lines = []
    
    global_ctx = read_context("_global")
    lines.append(f"=== GLOBAL CONTEXT ===\n{global_ctx}\n")
    
    if active_project:
        ctx = read_context(active_project)
        lines.append(f"=== ACTIVE PROJECT: {active_project} ===\n{ctx}\n")
        
        # Pick up any extra .md files in the project folder
        project_dir = PROJECTS_PATH / active_project
        for md_file in project_dir.glob("*.md"):
            if md_file.name == "_context.md":
                continue  # already loaded above
            lines.append(f"=== {md_file.stem.upper()} ===\n{md_file.read_text().strip()}\n")
    else:
        for p in projects:
            ctx = read_context(p)
            lines.append(f"=== PROJECT: {p} ===\n{ctx}\n")
    
    return "\n".join(lines)

def parse_and_apply_updates(response_text: str):
    import re

    # Auto-apply context updates (no approval needed)
    ctx_pattern = r'<update_context project="([^"]+)">(.*?)</update_context>'
    for project_name, content in re.findall(ctx_pattern, response_text, re.DOTALL):
        write_context(project_name, content.strip())
    clean = re.sub(ctx_pattern, '', response_text, flags=re.DOTALL).strip()

    # Approval-gated file updates
    file_pattern = r'<update_file project="([^"]+)" file="([^"]+)">(.*?)</update_file>'
    for project_name, filename, content in re.findall(file_pattern, clean, flags=re.DOTALL):
        print(f"\n  📄 SOL wants to update {project_name}/{filename}")
        print(f"  {'─'*40}")
        print(content.strip())
        print(f"  {'─'*40}")
        answer = input("  Apply? [y/n]: ").strip().lower()
        if answer == 'y':
            write_file(project_name, filename, content.strip())
        else:
            print("  ↳ skipped")
    clean = re.sub(file_pattern, '', clean, flags=re.DOTALL).strip()

    return clean

def chat(active_project: str | None = None):
    history = []
    project_label = active_project or "all projects"
    print(f"\n🗂  Syllabus — {project_label}")
    print("  type 'quit' to exit, 'switch <project>' to change focus\n")
    
    while True:
        user_input = input("you: ").strip()
        if not user_input:
            continue
        if user_input.lower() == 'quit':
            break
        if user_input.lower().startswith('switch '):
            active_project = user_input[7:].strip()
            print(f"  ↳ switched to {active_project}\n")
            continue
        
        # Build context-injected message
        ctx_block = build_context_block(active_project)
        augmented_input = f"{ctx_block}\n---\nUser message: {user_input}"
        
        history.append({"role": "user", "content": augmented_input})
        
        raw = ""

        match ACTIVE_MODEL:
            case "claude":
                print(f"\n{ACTIVE_MODEL}: ", end="", flush=True)
                raw = ""
                with client.messages.stream(
                    model="claude-sonnet-4-20250514",
                    max_tokens=1500,
                    system=SYSTEM_PROMPT,
                    messages=history
                ) as stream:
                    for text in stream.text_stream:
                        print(text, end="", flush=True)
                        raw += text
                print()

            case "llama3.2":
                print(f"\n{ACTIVE_MODEL}: ", end="", flush=True)
                raw = ""
                stream = client.chat.completions.create(
                    model="llama3.2",
                    messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
                    max_tokens=1500,
                    stream=True
                )
                for chunk in stream:
                    text = chunk.choices[0].delta.content or ""
                    print(text, end="", flush=True)
                    raw += text
                print()
            
            case _:
                pass # guarded by match-case at top level

        clean = parse_and_apply_updates(raw)
        
        # Store clean version in history to avoid context bloat
        history.append({"role": "assistant", "content": clean})
        

def main():
    projects = list_projects()
    
    if len(sys.argv) > 1:
        active = sys.argv[1]
    elif projects:
        print("Projects:", ", ".join(projects))
        active = input("Focus on project (or enter for all): ").strip() or None
    else:
        print("No projects found. Creating example structure...")
        (PROJECTS_PATH / "example-project").mkdir(parents=True, exist_ok=True)
        (PROJECTS_PATH / "example-project" / "_context.md").write_text("")
        active = "example-project"
    
    chat(active)

if __name__ == "__main__":
    main()