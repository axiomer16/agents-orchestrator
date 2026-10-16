"""Exécution des tâches de .agents/tasks/queue.json."""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .loader import load_registry
from .providers import chat, ProviderError
from .logger import get_logger, log_event

from typing import Any


MAX_CLARIFY = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_queue(root: Path) -> list[dict[str, Any]]:
    f = root / ".agents" / "tasks" / "queue.json"
    return json.loads(f.read_text()) if f.exists() else []


def save_queue(root: Path, queue: list[dict]) -> None:
    f = root / ".agents" / "tasks" / "queue.json"
    f.write_text(json.dumps(queue, indent=2, ensure_ascii=False))


def add_task(root: Path, goal: str, agent: str = "codeur",
             files: list[str] | None = None,
             depends_on: list[str] | None = None) -> dict:
    """Ajoute une tâche à la queue et journalise l'événement.

    Valide que chaque id de ``depends_on`` existe dans la queue actuelle ;
    une tâche dépendante d'un id inconnu est tout de même ajoutée mais
    marquée ``broken_dependency=True`` pour que l'utilisateur puisse corriger.
    """
    log = get_logger(root)
    queue = load_queue(root)
    known_ids = {t["id"] for t in queue}
    deps = list(depends_on or [])
    broken = [d for d in deps if d not in known_ids]
    if broken:
        log.warning("Tâche avec dépendances inconnues : %s", broken)
    task_id = f"task_{len(queue) + 1:03d}"
    task = {
        "id": task_id,
        "agent": agent,
        "goal": goal,
        "files": files or [],
        "depends_on": deps,
        "status": "pending",
        "attempts": 0,
        "clarify_attempts": 0,
        "created_at": _now(),
    }
    queue.append(task)
    save_queue(root, queue)
    log.info("Tâche ajoutée %s (agent=%s, depends_on=%s)",
             task_id, agent, deps)
    log_event(root, "task_added", id=task_id, agent=agent,
              goal=goal, depends_on=deps,
              broken_dependency=broken)
    return task


def _ready(task: dict[str, Any], queue: list[dict]) -> bool:
    """Une tâche est prête si :
    - son statut est ``pending`` ou ``retry`` ;
    - toutes ses dépendances (``depends_on``) sont ``done``.

    Les statuts ``failed`` / ``blocked`` d'une dépendance maintiennent la
    tâche en attente : on ne déclenche pas en chaîne un échec.
    """
    if task["status"] not in ("pending", "retry"):
        return False
    if not task.get("depends_on"):
        return True
    by_id = {t["id"]: t for t in queue}
    for dep_id in task["depends_on"]:
        dep = by_id.get(dep_id)
        if dep is None:
            return False  # dépendance manquante → bloqué
        if dep["status"] != "done":
            return False
    return True


def is_ready(task: dict[str, Any],
             all_tasks_by_id: dict[str, dict]) -> tuple[bool, str | None]:
    """Variante de ``_ready`` qui distingue l'attente normale d'un blocage définitif.

    Retourne ``(ready, reason)`` :

    * ``reason is None`` : la tâche attend simplement qu'une dépendance
      pending/retry se termine → on la laisse en l'état ;
    * ``reason`` non ``None`` : la dépendance est inconnue ou dans un état
      terminal d'échec (``blocked``/``failed``/``skipped``) → la tâche ne
      deviendra JAMAIS prête, l'appelant doit la passer en ``skipped``.

    Une dépendance ``done`` ne lève aucune raison.
    """
    if task.get("status") not in ("pending", "retry"):
        return False, None
    for dep_id in task.get("depends_on") or []:
        dep = all_tasks_by_id.get(dep_id)
        if dep is None:
            return False, f"dépendance inconnue : {dep_id}"
        st = dep.get("status")
        if st in ("blocked", "failed", "skipped"):
            return False, f"dépendance {dep_id} en échec"
        # pending / retry → on attend normalement, reason reste None
        # done → on continue
    return True, None


def _parse_json(raw: str) -> dict[str, Any]:
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Pas de JSON dans la réponse : {raw[:200]!r}")
    return json.loads(raw[start:end + 1])


def _apply_changes(root: Path, changes: list[dict], allowed: list[str]) -> list[str]:
    """Écrit les fichiers proposés. Refuse tout chemin hors projet ou hors périmètre."""
    log = get_logger(root)
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
        log_event(root, "tool_call", tool="write_file", path=rel)
    return written


def _log(root: Path, task: dict[str, Any], prompt: str, raw: str) -> None:
    d = root / ".agents" / "tasks" / "log"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{task['id']}_{task['attempts']}.md").write_text(
        f"# {task['id']} — {task['agent']} — {_now()}\n\n"
        f"## Prompt\n\n{prompt}\n\n## Réponse brute\n\n{raw}\n"
    )


def list_project_files(project_root: Path, limit: int = 200) -> list[str]:
    """Liste les fichiers texte du projet (max ``limit``).

    Ignore ``.git``, ``__pycache__``, ``.agents``, ``node_modules`` et
    tout ce qui n'est pas un fichier d'extension texte courante.
    """
    ignore = {".git", "__pycache__", ".agents", "node_modules"}
    text_exts = {
        ".py", ".md", ".txt", ".json", ".yml", ".yaml", ".toml",
        ".js", ".ts", ".html", ".css", ".sh", ".cfg", ".ini", ".rst",
    }
    root = Path(project_root).resolve()
    files: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(root).parts
        if any(part in ignore for part in rel_parts):
            continue
        if p.suffix.lower() in text_exts:
            files.append(str(p.relative_to(root)))
            if len(files) >= limit:
                break
    return files


def _is_blocked(task: dict, queue: list[dict]) -> bool:
    """Vrai si la tâche dépend d'un id inexistant ou d'une tâche non-``done``."""
    if not task.get("depends_on"):
        return False
    by_id = {t["id"]: t for t in queue}
    return any(
        by_id.get(d) is None or by_id[d]["status"] != "done"
        for d in task["depends_on"]
    )


def ask_maestro(task: dict, reason: str, project_root: Path) -> dict[str, Any] | None:
    """Demande au rôle ``maestro`` de reformuler ``goal`` / ``files``.

    Reproduit le même mécanisme d'appel modèle que ``run_task`` (mêmes
    résolutions provider/model/fallback, mêmes options, même parsing JSON).
    Renvoie le dict parsé ou ``None`` si le modèle est indisponible ou si
    la réponse ne contient pas de JSON exploitable.
    """
    log = get_logger(project_root)
    try:
        reg = load_registry(project_root)
    except Exception as e:
        print(f"[DEBUG] ask_maestro: registre indisponible ({e})")
        return None
    role = reg.roles.get("maestro")
    if role is None:
        print(f"[DEBUG] ask_maestro: rôle 'maestro' introuvable dans le registre")
        return None

    system = role.build_prompt(reg.skills, reg.context)
    files_list = list_project_files(project_root)
    user = (
        f"Une tâche vient d'être bloquée et a besoin d'être clarifiée.\n\n"
        f"Tâche : {task['id']}\n"
        f"Goal actuel : {task['goal']}\n"
        f"Files actuels : {task['files']}\n"
        f"Raison du blocage : {reason}\n\n"
        f"Fichiers texte du projet (extrait, max 200) :\n"
        f"{chr(10).join(files_list) if files_list else '(aucun)'}\n\n"
        "Réponds STRICTEMENT par un JSON valide (sans markdown, sans texte "
        'autour) de la forme {"goal": "...", "files": ["chemin/relatif", ...]}. '
        "Pas de clé 'changes', pas de 'status'. Juste ces deux clés."
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
    opts = {k: getattr(role, k) for k in ("num_ctx", "temperature")
            if getattr(role, k, None) is not None}
    json_mode = getattr(role, "output_format", "json") != "text"
    timeout = getattr(role, "timeout", 300)

    log.info("[DEBUG] clarification maestro demandée pour %s (reason=%s)",
             task["id"], reason)
    log_event(project_root, "clarify_request", id=task["id"], reason=reason,
              provider=provider, model=model)
    for m in [x for x in (model, fallback) if x]:
        try:
            raw = chat(provider, m, system, user,
                       json_mode=json_mode, timeout=timeout, **opts)
            log_event(project_root, "model_call", id=task["id"], provider=provider,
                      model=m, role="maestro")
            return _parse_json(raw)
        except (ProviderError, ValueError, json.JSONDecodeError) as e:
            print(f"[DEBUG] ask_maestro: modèle {m} a échoué ({e})")
            continue
    return None


def _maybe_clarify(root: Path, task: dict, console) -> None:
    """Boucle de rattrapage ``maestro`` quand ``run_task`` revient ``blocked``.

    * Max ``MAX_CLARIFY`` tentatives (compteur ``task["clarify_attempts"]``).
    * Si clarification OK → ``task["goal"]`` / ``task["files"]`` mis à jour,
      statut repassé à ``retry`` (la tâche sera reprise au tour suivant,
      pas dans le même appel).
    * Si clarification KO (parse / schéma) → on incrémente quand même le
      compteur (la tentative est comptée comme échouée).
    * Si le compteur atteint ``MAX_CLARIFY`` → statut ``blocked`` définitif.
    """
    log = get_logger(root)
    task.setdefault("clarify_attempts", 0)
    if task["status"] != "blocked":
        return
    if task["clarify_attempts"] >= MAX_CLARIFY:
        log.warning(
            "[DEBUG] %s bloquée définitivement après %d tentative(s) de clarification",
            task["id"], task["clarify_attempts"],
        )
        log_event(root, "clarify_failed", id=task["id"],
                  attempts=task["clarify_attempts"], reason="max_reached")
        return

    reason = task.get("error") or "raison inconnue"
    log.info("[DEBUG] clarification maestro pour %s (essai %d/%d)",
             task["id"], task["clarify_attempts"] + 1, MAX_CLARIFY)
    answer = ask_maestro(task, reason, root)

    if answer is None:
        task["clarify_attempts"] += 1
        log.warning(
            "[DEBUG] maestro n'a pas renvoyé de JSON exploitable pour %s",
            task["id"],
        )
        log_event(root, "clarify_failed", id=task["id"],
                  attempts=task["clarify_attempts"], reason="no_json")
        return

    new_goal = answer.get("goal")
    new_files = answer.get("files")
    if not isinstance(new_goal, str) or not isinstance(new_files, list):
        task["clarify_attempts"] += 1
        log.warning(
            "[DEBUG] maestro a renvoyé un JSON mal formé pour %s (clés=%s)",
            task["id"], sorted(answer.keys()),
        )
        log_event(root, "clarify_failed", id=task["id"],
                  attempts=task["clarify_attempts"], reason="bad_schema")
        return

    old_goal = task["goal"]
    task["goal"] = new_goal
    task["files"] = [str(f) for f in new_files
                     if isinstance(f, (str, Path))]
    task["clarify_attempts"] += 1
    task["status"] = "retry"
    task["error"] = None
    log.info("[DEBUG] task_clarified %s : '%s' -> '%s'",
             task["id"], old_goal, new_goal)
    log_event(root, "task_clarified", id=task["id"],
              old_goal=old_goal, new_goal=new_goal,
              attempts=task["clarify_attempts"])


def run_task(root: Path, task: dict[str, Any], console) -> dict:
    log = get_logger(root)
    reg = load_registry(root)
    role = reg.roles.get(task["agent"])
    if role is None:
        task["status"], task["error"] = "failed", f"Rôle inconnu : {task['agent']}"
        log.error("Rôle inconnu : %s", task["agent"])
        log_event(root, "task_end", id=task["id"], status="failed",
                  error=task["error"])
        return task

    # Vérification du chaînage : si une dépendance n'est pas ``done``,
    # on bloque plutôt que d'appeler le modèle.
    queue = load_queue(root)
    if _is_blocked(task, queue):
        task["status"] = "blocked"
        task["error"] = (
            f"Dépendance non terminée : {[d for d in task['depends_on']]}"
        )
        log.warning("Tâche %s bloquée (dépendances)", task["id"])
        log_event(root, "task_blocked", id=task["id"], depends_on=task["depends_on"])
        return task

    system = role.build_prompt(reg.skills, reg.context)
    user = (
        f"Tâche {task['id']} : {task['goal']}\n"
        f"Fichiers concernés : {task['files'] or 'à ta discrétion'}\n\n"
        "Si tu dois créer ou modifier des fichiers, ajoute dans ton JSON la clé "
        '"changes": [{"path": "chemin/relatif", "content": "contenu complet du fichier"}].'
    )
    log.info("Prompt composé pour %s (%d skills injectés)",
             task["id"], len(role.skills))
    log_event(root, "prompt_built", id=task["id"], agent=task["agent"],
              skills=[s for s in role.skills if s in reg.skills],
              missing_skills=[s for s in role.skills if s not in reg.skills])

    provider = getattr(role, "provider", None) or "ollama"
    model = getattr(role, "model", None)
    if not model:
        alias_model, alias_provider = reg.resolve_model(role)
        if not alias_model.startswith("["):        # alias trouvé
            model = alias_model
            provider = provider or alias_provider
    provider = provider or "ollama"
    fallback = getattr(role, "fallback", None)
    opts = {k: getattr(role, k) for k in ("num_ctx", "temperature")
            if getattr(role, k, None) is not None}
    json_mode = getattr(role, "output_format", "json") != "text"
    timeout = getattr(role, "timeout", 300)

    task["attempts"] += 1
    task["started_at"] = _now()
    log_event(root, "task_start", id=task["id"], agent=task["agent"],
              attempt=task["attempts"], provider=provider, model=model)
    for m in [x for x in (model, fallback) if x]:
        console.print(f"[cyan]→ {task['id']}[/] {task['agent']} via {provider}/{m}…")
        t0 = datetime.now(timezone.utc)
        try:
            raw = chat(provider, m, system, user,
                       json_mode=json_mode, timeout=timeout, **opts)
            duration = (datetime.now(timezone.utc) - t0).total_seconds()
            log_event(root, "model_call", id=task["id"], provider=provider,
                      model=m, duration_s=duration, json_mode=json_mode)
            _log(root, task, system + "\n\n---\n\n" + user, raw)
            result: dict[str, Any] = _parse_json(raw) if json_mode else {
                "status": "done", "summary": raw}
            changes = result.get("changes")
            if isinstance(changes, list):
                result["files"] = _apply_changes(root, changes, task["files"])
                # un modèle qui livre des fichiers sans dire "done" a quand même travaillé
                result.setdefault("status", "done")

            if result.get("status") not in ("done", "blocked", "failed"):
                task["error"] = (
                    f"Réponse sans 'status' valide. Clés reçues : {sorted(result)}. "
                    f"Début : {raw[:200]!r}"
                )
                console.print(f"[yellow]  ⚠ {task['error']}[/]")
                result["status"] = "failed"

            task["status"] = result["status"]
            task["result"] = {k: v for k, v in result.items() if k != "changes"}
            task["model_used"] = m
            log.info("Tâche %s → %s (model=%s, %.1fs)",
                     task["id"], task["status"], m, duration)
            log_event(root, "task_end", id=task["id"], status=task["status"],
                      model=m, duration_s=duration)
            break
        except (ProviderError, ValueError, PermissionError, json.JSONDecodeError) as e:
            task["error"] = str(e)
            console.print(f"[yellow]  ⚠ {e}[/]")
            log.error("Tâche %s échouée : %s", task["id"], e)
            task["status"] = "failed"
    else:  # aucun modèle n'a été essayé
        task["status"] = "blocked"
        task["error"] = (
            f"Aucun modèle configuré pour {task['agent']} "
            f"(model={model}, fallback={fallback})"
        )
        log_event(root, "task_blocked", id=task["id"], reason="no_model")

    max_retries = getattr(role, "max_retries", 2)
    if task["status"] == "failed" and task["attempts"] <= max_retries:
        task["status"] = "retry"
        log_event(root, "task_retry", id=task["id"], attempt=task["attempts"])
    task["finished_at"] = _now()
    return task


def run_queue(root: Path, console, only: str | None = None,
              max_loops: int = 20) -> None:
    log = get_logger(root)
    for _ in range(max_loops):
        queue = load_queue(root)
        by_id = {t["id"]: t for t in queue}
        todo: list[dict] = []

        # 1) marquer ``skipped`` les tâches qui ne deviendront jamais prêtes
        for t in queue:
            if only is not None and t["id"] != only:
                continue
            if t.get("status") not in ("pending", "retry"):
                continue
            ready, reason = is_ready(t, by_id)
            if ready:
                todo.append(t)
            elif reason is not None:
                t["status"] = "skipped"
                t["error"] = reason
                t.setdefault("clarify_attempts", 0)
                log.warning("[DEBUG] task_skipped %s : %s", t["id"], reason)
                log_event(root, "task_skipped", id=t["id"], reason=reason)

        # 2) rien à exécuter ce tour ?
        if not todo:
            remaining = [t for t in queue
                         if t.get("status") in ("pending", "retry")]
            if not remaining:
                log.info("Plus rien à exécuter (filtre=%s)", only)
                break
            log.info("[DEBUG] rien d'exécutable ce tour (%d tâche(s) en attente "
                     "de dépendances pending/retry), on continue", len(remaining))
            continue

        # 3) exécuter toutes les tâches prêtes de ce tour (pas seulement
        # la première) ; pour chacune, on tente ensuite la clarification
        # maestro si elle revient ``blocked``.
        for task in todo:
            task.setdefault("attempts", 0)
            task.setdefault("clarify_attempts", 0)
            run_task(root, task, console)
            _maybe_clarify(root, task, console)
            save_queue(root, queue)
            color = {"done": "green", "blocked": "magenta",
                     "retry": "yellow"}.get(task["status"], "red")
            summary = (task.get("result", {}).get("summary")
                       or task.get("error", ""))
            console.print(f"[{color}]  {task['status'].upper()}[/] — {summary}")
            if only and task["status"] != "retry":
                return
