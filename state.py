import json
from datetime import date

import brain
import vault

STATE_PATH = vault.VAULT_PATH / "_sol_state.json"
DEFAULT_DRIFT_THRESHOLD_WEEKS = 4
VALID_MODELS = set(brain.ANTHROPIC_MODELS) | {"llama"}


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"active_focus": None, "deferred": [], "active_model": None}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    op = "updated" if STATE_PATH.exists() else "created"
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    vault._log_operation(op, STATE_PATH.relative_to(vault.VAULT_PATH))


def set_model(model_name: str, state: dict) -> dict:
    if model_name not in VALID_MODELS:
        raise ValueError(f"Unknown model '{model_name}' — valid options: {', '.join(sorted(VALID_MODELS))}")
    state["active_model"] = model_name
    return state


def set_focus(project: str, state: dict) -> dict:
    previous = state.get("active_focus")
    if previous and previous != project:
        state.setdefault("deferred", []).append({
            "project": previous,
            "deferred_date": date.today().isoformat(),
            "reason": f"pivoting to {project}",
            "drift_threshold_weeks": DEFAULT_DRIFT_THRESHOLD_WEEKS,
        })
    state["active_focus"] = project
    return state


def check_drift(state: dict) -> list[str]:
    messages = []
    today = date.today()
    for item in state.get("deferred", []):
        weeks_deferred = (today - date.fromisoformat(item["deferred_date"])).days // 7
        if weeks_deferred >= item["drift_threshold_weeks"]:
            messages.append(
                f"It's been {weeks_deferred} weeks since you shelved {item['project']} — "
                f"still on hold, or worth pulling back in?"
            )
            item["drift_threshold_weeks"] += 2
    return messages
