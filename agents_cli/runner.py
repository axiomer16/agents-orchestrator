"""Exécution des tâches de .agents/tasks/queue.json."""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .loader import load_registry
from .providers import chat, ProviderError

from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_queue(root: Path) -> list[dict[str, Any]]:
    f = root / ".agents" / "tasks" / "queue.json"
    return json.loads(f.read_text()) if f.exists() else []


def save_queue(root: Path, queue: list[dict]) -> None:
    f = root / ".agents" / "tasks" / "queue.json"
    f.write_text(json.dumps(queue, indent=2, ensure_ascii=False))


def add_task(root: Path, goal: str, agent: str = "codeur",
             files: list[str] | None = None, depends_on: list[str] | None = None) -> dict:
    queue = load_queue(root)
    task = {
        "id": f"task_{len(queue) + 1:03d}",
        "agent": agent,
        "goal": goal,
        "files": files or [],
        "depends_on": depends_on or [],
        "status": "pending",
        "attempts": 0,
        "created_at": _now(),
    }
    queue.append(task)
    save_queue(root, queue)
    return task


def _ready(task: dict[str, Any], queue: list[dict]) -> bool:
    done = {t["id"] for t in queue if t["status"] == "done"}
    return task["status"] in ("pending", "retry") and set(task["depends_on"]) <= done


def _parse_json(raw: str) -> dict[str, Any]:
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Pas de JSON dans la réponse : {raw[:200]!r}")
    return json.loads(raw[start:end + 1])


def _apply_changes(root: Path, changes: list[dict], allowed: list[str]) -> list[str]:
    """Écrit les fichiers proposés. Refuse tout chemin hors projet ou hors périmètre."""
    written = []
    for ch in changes:
        rel = ch.get("path", "")
        target = (root / rel).resolve()
        if root.resolve() not in target.parents:
            raise PermissionError(f"Chemin hors projet refusé : {rel}")
        if allowed and rel not in allowed:
            raise PermissionError(f"Fichier hors périmètre de la tâche : {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(ch.get("content", ""))
        written.append(rel)
    return written


def _log(root: Path, task: dict[str, Any], prompt: str, raw: str) -> None:
    d = root / ".agents" / "tasks" / "log"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{task['id']}_{task['attempts']}.md").write_text(
        f"# {task['id']} — {task['agent']} — {_now()}\n\n"
        f"## Prompt\n\n{prompt}\n\n## Réponse brute\n\n{raw}\n")


def run_task(root: Path, task: dict[str, Any], console) -> dict:
    reg = load_registry(root)
    role = reg.roles.get(task["agent"])
    if role is None:
        task["status"], task["error"] = "failed", f"Rôle inconnu : {task['agent']}"
        return task

    system = role.build_prompt(reg.skills, reg.context)
    user = (
        f"Tâche {task['id']} : {task['goal']}\n"
        f"Fichiers concernés : {task['files'] or 'à ta discrétion'}\n\n"
        "Si tu dois créer ou modifier des fichiers, ajoute dans ton JSON la clé "
        '"changes": [{"path": "chemin/relatif", "content": "contenu complet du fichier"}].'
    )
    provider = getattr(role, "provider", None) or "ollama"
    model = getattr(role, "model", None)
    if not model:
            alias_model, alias_provider = reg.resolve_model(role)
            if not alias_model.startswith("["):        # alias trouvé
                model = alias_model
                provider = provider or alias_provider
    provider = provider or "ollama"
    fallback = getattr(role, "fallback", None)
    opts = {k: getattr(role, k) for k in ("num_ctx", "temperature") if getattr(role, k, None)}
    json_mode = getattr(role, "output_format", "json") != "text"
    timeout = getattr(role, "timeout", 300)

    task["attempts"] += 1
    task["started_at"] = _now()
    for m in [x for x in (model, fallback) if x]:
        console.print(f"[cyan]→ {task['id']}[/] {task['agent']} via {provider}/{m}…")
        try:
            raw = chat(provider, m, system, user, json_mode=json_mode, timeout=timeout, **opts)
            _log(root, task, system + "\n\n---\n\n" + user, raw)
            result: dict[str, Any] = _parse_json(raw) if json_mode else {"status": "done", "summary": raw}
            changes = result.get("changes")
            if isinstance(changes, list):
                result["files"] = _apply_changes(root, changes, task["files"])
                # un modèle qui livre des fichiers sans dire "done" a quand même travaillé
                result.setdefault("status", "done")

            if result.get("status") not in ("done", "blocked", "failed"):
                task["error"] = (f"Réponse sans 'status' valide. Clés reçues : {sorted(result)}. "
                                    f"Début : {raw[:200]!r}")
                console.print(f"[yellow]  ⚠ {task['error']}[/]")
                result["status"] = "failed"

            task["status"] = result["status"]
            task["result"] = {k: v for k, v in result.items() if k != "changes"}
            task["model_used"] = m
            break
        except (ProviderError, ValueError, PermissionError, json.JSONDecodeError) as e:
            task["error"] = str(e)
            console.print(f"[yellow]  ⚠ {e}[/]")
            task["status"] = "failed"
    else:  # ← La boucle for ne s'est pas exécutée
        task["status"] = "blocked"
        task["error"] = f"Aucun modèle configuré pour {task['agent']} (model={model}, fallback={fallback})"

    max_retries = getattr(role, "max_retries", 2)
    if task["status"] == "failed" and task["attempts"] <= max_retries:
        task["status"] = "retry"
    task["finished_at"] = _now()
    return task


def run_queue(root: Path, console, only: str | None = None, max_loops: int = 20) -> None:
    for _ in range(max_loops):
        queue = load_queue(root)
        todo = [t for t in queue if _ready(t, queue) and (only is None or t["id"] == only)]
        if not todo:
            break
        task = todo[0]
        task.setdefault("attempts", 0)
        run_task(root, task, console)
        save_queue(root, queue)
        color = {"done": "green", "blocked": "magenta", "retry": "yellow"}.get(task["status"], "red")
        console.print(f"[{color}]  {task['status'].upper()}[/] — "
                      f"{task.get('result', {}).get('summary') or task.get('error', '')}")
        if only and task["status"] != "retry":
            break
