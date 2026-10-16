from __future__ import annotations
from pathlib import Path
import yaml
import re
from agents_cli.models import Role, Skill
from agents_cli.logger import get_logger, log_event
from dataclasses import dataclass


DEFAULTS = Path(__file__).parent

log = get_logger  # alias court pour les appels locaux


def _load_skills(directory: Path, project_root: Path | None = None) -> dict[str, Skill]:
    """Charge les skills depuis ``<directory>/*/SKILL.md``.

    Ignore silencieusement les dossiers sans SKILL.md et journalise
    chaque skill chargé pour qu'on puisse vérifier qu'ils sont bien
    injectés dans le prompt de l'agent.
    """
    if not directory.exists():
        return {}
    skills: dict[str, Skill] = {}
    for path in sorted(directory.glob("*/SKILL.md")):
        skill = Skill.from_file(path)
        skills[skill.name] = skill
        if project_root is not None:
            log_event(
                project_root,
                "skill_loaded",
                name=skill.name,
                source=str(path),
                description=skill.description[:120],
            )
    return skills


def _load_roles(directory: Path, project_root: Path | None = None) -> dict[str, Role]:
    """Charge les rôles depuis ``<directory>/*.{md,yaml,yml}``.

    Frontmatter YAML entre ``---`` pour les .md, ou directement YAML pour
    les .yaml/.yml avec un champ ``system_prompt`` (string ou ``|``).
    """
    roles: dict[str, Role] = {}
    if not directory.exists():
        return roles
    for path in sorted(list(directory.glob("*.md")) +
                       list(directory.glob("*.yaml")) +
                       list(directory.glob("*.yml"))):
        text = path.read_text(encoding="utf-8")
        meta: dict = {}
        prompt = ""
        if path.suffix == ".md":
            m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
            if not m:
                continue
            meta = yaml.safe_load(m.group(1)) or {}
            prompt = m.group(2).strip()
        else:
            data = yaml.safe_load(text) or {}
            meta = {k: v for k, v in data.items() if k != "system_prompt"}
            prompt = (data.get("system_prompt") or "").strip()
        if not prompt:
            continue
        name = meta.get("name", path.stem)
        role = Role(
            name=name,
            description=meta.get("description", ""),
            system_prompt=prompt,
            model_alias=meta.get("model_alias", "default"),
            skills=meta.get("skills", []) or [],
        )
        roles[name] = role
        if project_root is not None:
            log_event(
                project_root,
                "role_loaded",
                name=name,
                source=str(path),
                skills=role.skills,
            )
    return roles


def _load_models(agents_dir: Path) -> tuple[dict, dict]:
    path = agents_dir / "models.yaml"
    if not path.exists():
        return {}, {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("models", {}), data.get("providers", {})


@dataclass
class Registry:
    roles: dict[str, Role]
    skills: dict[str, Skill]
    context: str
    aliases: dict[str, dict[str, str]]
    providers: dict[str, str]

    def resolve_model(self, role: Role) -> tuple[str, str]:
        lookup_key = role.model_alias if role.model_alias else role.name
        entry = self.aliases.get(lookup_key)
        if entry is None:
            return f"[alias absent: {lookup_key}]", "-"
        return entry.get("model", "?"), entry.get("provider", "ollama")


def load_registry(project_root: Path) -> Registry:
    """Charge les défauts de l'orchestrateur, surchargés par le .agents/ du projet.

    Journalise chaque étape dans ``.agents/logs/agents-YYYY-MM-DD.log`` et
    émet un événement ``registry_built`` dans ``events.jsonl``.
    """
    logger = get_logger(project_root)
    agents_dir = project_root / ".agents"

    logger.info("Chargement du registre pour %s", project_root)

    skills = _load_skills(DEFAULTS / "skills", project_root)
    skills.update(_load_skills(agents_dir / "skills", project_root))

    roles = _load_roles(DEFAULTS / "roles", project_root)
    roles.update(_load_roles(agents_dir / "agents", project_root))

    context_file = agents_dir / "project.md"
    context = context_file.read_text(encoding="utf-8") if context_file.exists() else ""

    models_yaml = agents_dir / "models.yaml"
    data = (
        yaml.safe_load(models_yaml.read_text(encoding="utf-8"))
        if models_yaml.exists()
        else {}
    ) or {}

    for agent_name, agent_cfg in (data.get("agents") or {}).items():
        if agent_name in roles:
            role = roles[agent_name]
            role.model = agent_cfg.get("model") or role.model
            role.provider = agent_cfg.get("provider") or role.provider
            role.fallback = agent_cfg.get("fallback")
            role.num_ctx = agent_cfg.get("num_ctx")
            role.temperature = agent_cfg.get("temperature")
            role.timeout = agent_cfg.get("timeout")
            logger.info(
                "Agent %s configuré (model=%s, provider=%s)",
                agent_name, role.model, role.provider,
            )

    log_event(
        project_root,
        "registry_built",
        roles=list(roles),
        skills=list(skills),
        has_context=bool(context),
    )

    return Registry(
        roles=roles,
        skills=skills,
        context=context,
        aliases=data.get("aliases", {}),
        providers=data.get("providers", {}),
    )
