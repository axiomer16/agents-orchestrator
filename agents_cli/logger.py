"""Journalisation structurée de l'orchestrateur.

- Fichier texte journalier : ``.agents/logs/agents-YYYY-MM-DD.log``
  Format : ``timestamp niveau module message``
- Fichier JSONL d'événements : ``.agents/logs/events.jsonl``
  Un événement par ligne, pour relecture machine (tâches, modèles, skills, outils).

API publique :
- :func:`get_logger(project_root)` retourne un :class:`logging.Logger`
  configuré (idempotent : appelable plusieurs fois sans dupliquer les handlers).
- :func:`log_event(kind, **data)` écrit un événement JSONL.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

LOG_DIRNAME = "logs"
LOG_PREFIX = "agents"
EVENTS_FILENAME = "events.jsonl"
DEFAULT_LEVEL = os.environ.get("AGENTS_LOG_LEVEL", "INFO").upper()


class JsonFormatter(logging.Formatter):
    """Sérialise chaque record en JSONL sur stdout/stderr si besoin."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _log_dir(project_root: Path) -> Path:
    """Crée ``<root>/.agents/logs`` et le retourne."""
    d = project_root / ".agents" / LOG_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_logger(project_root: Path) -> logging.Logger:
    """Logger nommé ``agents`` avec handler fichier quotidien.

    Le handler utilise ``.agents/logs/agents-YYYY-MM-DD.log`` et la rotation est
    gérée par le nom du fichier (un fichier par date).
    """
    logger = logging.getLogger("agents")
    # Idempotence : si déjà configuré pour ce root, on ne ré-ajoute pas de handlers.
    for h in logger.handlers:
        if getattr(h, "_agents_root", None) == str(project_root):
            return logger
    logger.setLevel(DEFAULT_LEVEL)
    logger.propagate = False

    log_dir = _log_dir(project_root)
    today = date.today().isoformat()
    log_path = log_dir / f"{LOG_PREFIX}-{today}.log"

    fmt = "%(asctime)s %(levelname)-5s %(name)s %(module)s:%(lineno)d %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%S%z"
    formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler._agents_root = str(project_root)  # type: ignore[attr-defined]
    logger.addHandler(file_handler)

    return logger


def log_event(project_root: Path, kind: str, **data: Any) -> None:
    """Ajoute un événement JSONL dans ``.agents/logs/events.jsonl``.

    `kind` est une étiquette courte (``task_start``, ``task_end``,
    ``task_retry``, ``task_blocked``, ``model_call``, ``skill_loaded``,
    ``tool_call``…). Les autres arguments sont fusionnés dans le payload.
    """
    log_dir = _log_dir(project_root)
    event: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "kind": kind,
    }
    event.update(data)
    line = json.dumps(event, ensure_ascii=False)
    with (log_dir / EVENTS_FILENAME).open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
