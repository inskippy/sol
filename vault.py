import difflib
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
VAULT_PATH = Path(os.environ.get("VAULT_PATH")).resolve()
PROJECTS_PATH = VAULT_PATH / "projects"
GLOBAL_CONTEXT = VAULT_PATH / "_global_context.md"
GLOBAL_TODO = VAULT_PATH / "_global_todo.md"
SOL_LOG = VAULT_PATH / "_sol_log.md"

_context_backups: dict[str, str] = {}


class VaultPathError(Exception):
    pass


def _ensure_in_vault(path: Path) -> Path:
    resolved = path.resolve()
    if not str(resolved).startswith(str(VAULT_PATH)):
        raise VaultPathError(f"blocked operation outside vault: {resolved}")
    return resolved


def _log_operation(op: str, rel_path: Path) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(SOL_LOG, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} | {op:<8} | {rel_path.as_posix()}\n")


def _context_path(project_name: str) -> Path:
    if project_name == "_global":
        return GLOBAL_CONTEXT
    return PROJECTS_PATH / project_name / "_context.md"


def list_projects() -> list[str]:
    if not PROJECTS_PATH.exists():
        return []
    return [p.name for p in PROJECTS_PATH.iterdir() if p.is_dir()]


def read_context(project_name: str) -> str:
    path = _context_path(project_name)
    if path.exists():
        content = path.read_text(encoding="utf-8").strip()
        return content if content else "(empty)"
    return "(no context file found)"


def read_file(project_name: str, filename: str) -> str:
    path = PROJECTS_PATH / project_name / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return "(file not found)"


def build_context_block(active_project: str | None) -> str:
    lines = [f"=== GLOBAL CONTEXT ===\n{read_context('_global')}\n"]

    if active_project:
        lines.append(f"=== ACTIVE PROJECT: {active_project} ===\n{read_context(active_project)}\n")
        project_dir = PROJECTS_PATH / active_project
        for md_file in sorted(project_dir.glob("*.md")):
            if md_file.name == "_context.md":
                continue
            lines.append(f"=== {md_file.stem.upper()} ===\n{md_file.read_text(encoding='utf-8').strip()}\n")
    else:
        for project in list_projects():
            lines.append(f"=== PROJECT: {project} ===\n{read_context(project)}\n")

    return "\n".join(lines)


def read_all_contexts() -> str:
    lines = [f"=== GLOBAL CONTEXT ===\n{read_context('_global')}\n"]
    for project in list_projects():
        lines.append(f"=== PROJECT: {project} ===\n{read_context(project)}\n")
    return "\n".join(lines)


def write_context(project_name: str, content: str) -> None:
    path = _ensure_in_vault(_context_path(project_name))
    op = "updated" if path.exists() else "created"
    if path.exists():
        _context_backups[project_name] = path.read_text(encoding="utf-8")

    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    path.write_text(f"*Last updated: {timestamp}*\n\n{content}", encoding="utf-8")
    _log_operation(op, path.relative_to(VAULT_PATH))


def revert_context(project_name: str) -> bool:
    if project_name not in _context_backups:
        return False
    path = _ensure_in_vault(_context_path(project_name))
    path.write_text(_context_backups.pop(project_name), encoding="utf-8")
    _log_operation("reverted", path.relative_to(VAULT_PATH))
    return True


def preview_file_write(project_name: str, filename: str, new_content: str) -> str:
    path = PROJECTS_PATH / project_name / filename
    if not path.exists():
        return "(new file)"
    old_content = path.read_text(encoding="utf-8")
    diff = difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    )
    return "".join(diff) or "(no changes)"


def write_file(project_name: str, filename: str, content: str) -> None:
    path = _ensure_in_vault(PROJECTS_PATH / project_name / filename)
    op = "updated" if path.exists() else "created"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _log_operation(op, path.relative_to(VAULT_PATH))


def append_file(project_name: str, filename: str, content: str) -> None:
    path = _ensure_in_vault(PROJECTS_PATH / project_name / filename)
    op = "updated" if path.exists() else "created"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    separator = f"\n\n*Added {timestamp}*\n" if existing else f"*Added {timestamp}*\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(existing + separator + content, encoding="utf-8")
    _log_operation(op, path.relative_to(VAULT_PATH))


def append_global_todo(items: list[tuple[str, str]]) -> None:
    if not items:
        return
    path = _ensure_in_vault(GLOBAL_TODO)
    op = "updated" if path.exists() else "created"
    existing = path.read_text(encoding="utf-8") if path.exists() else "## inbox\n"
    new_lines = "".join(f"* [ ] {item} ({project})\n" for project, item in items)

    path.write_text(existing + new_lines, encoding="utf-8")
    _log_operation(op, path.relative_to(VAULT_PATH))


def delete_file(project_name: str, filename: str) -> None:
    path = _ensure_in_vault(PROJECTS_PATH / project_name / filename)
    if path.exists():
        path.unlink()
        _log_operation("deleted", path.relative_to(VAULT_PATH))
