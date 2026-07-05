import sys

import brain
import state
import vault


def build_context_block(active_project: str | None) -> str:
    lines = [f"=== GLOBAL CONTEXT ===\n{vault.read_context('_global')}\n"]

    if active_project:
        lines.append(f"=== ACTIVE PROJECT: {active_project} ===\n{vault.read_context(active_project)}\n")
        project_dir = vault.PROJECTS_PATH / active_project
        for md_file in sorted(project_dir.glob("*.md")):
            if md_file.name == "_context.md":
                continue
            lines.append(f"=== {md_file.stem.upper()} ===\n{md_file.read_text(encoding='utf-8').strip()}\n")
    else:
        for project in vault.list_projects():
            lines.append(f"=== PROJECT: {project} ===\n{vault.read_context(project)}\n")

    return "\n".join(lines)


def switch_project(project_name: str) -> None:
    current_state = state.load_state()
    state.set_focus(project_name, current_state)
    state.save_state(current_state)


def chat(active_project: str | None = None) -> None:
    history = []
    last_context_project = None
    project_label = active_project or "all projects"
    print(f"\nSyllabus - {project_label}")
    print("  type 'quit' to exit, 'switch <project>' to change focus, 'r' to revert last context update\n")

    while True:
        user_input = input("you: ").strip()
        if not user_input:
            continue
        if user_input.lower() == 'quit':
            break
        if user_input.lower() == 'r':
            if last_context_project and vault.revert_context(last_context_project):
                print(f"  -> reverted {last_context_project}/_context.md")
            else:
                print("  -> nothing to revert")
            continue
        if user_input.lower().startswith('switch '):
            active_project = user_input[7:].strip()
            switch_project(active_project)
            print(f"  -> switched to {active_project}\n")
            continue

        ctx_block = build_context_block(active_project)
        augmented_input = f"{ctx_block}\n---\nUser message: {user_input}"
        history.append({"role": "user", "content": augmented_input})

        print("\nsol: ", end="", flush=True)
        raw = ""
        for text in brain.think_stream(history):
            print(text, end="", flush=True)
            raw += text
        print()

        clean, context_updates, file_updates = brain.parse_updates(raw)

        for project, content in context_updates:
            vault.write_context(project, content)
            last_context_project = project
            print(f"  -> updated {project}/_context.md - type 'r' to revert")

        for project, filename, content in file_updates:
            diff = vault.preview_file_write(project, filename, content)
            print(f"\n  SOL wants to update {project}/{filename}")
            print(f"  {'-' * 40}")
            print(content if diff == '(new file)' else diff)
            print(f"  {'-' * 40}")
            answer = input("  Apply? [y/n]: ").strip().lower()
            if answer == 'y':
                vault.write_file(project, filename, content)
            else:
                print("  -> skipped")

        history.append({"role": "assistant", "content": clean})


def main() -> None:
    projects = vault.list_projects()

    if len(sys.argv) > 1:
        active = sys.argv[1]
    elif projects:
        print("Projects:", ", ".join(projects))
        active = input("Focus on project (or enter for all): ").strip() or None
    else:
        print("No projects found. Creating example structure...")
        vault.write_context("example-project", "")
        active = "example-project"

    if active:
        switch_project(active)

    chat(active)


if __name__ == "__main__":
    main()
