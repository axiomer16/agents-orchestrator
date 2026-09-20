from __future__ import annotations
from pathlib import Path
from platform import system_alias
import yaml
import re
from agents_cli.models import Role, Skill
from dataclasses import dataclass, fields
import inspect


DEFAULTS = Path(__file__).parent


def _load_skills(directory: Path) -> dict[str, Skill]:
    if not directory.exists():
        return {}
    return {
        skill.name: skill
        for skill in (Skill.from_file(p) for p in directory.glob("*/SKILL.md"))
    }


def _load_roles(directory: Path) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    if not directory.exists():
        return roles
    for path in sorted(directory.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
        if not m:
            continue
        meta = yaml.safe_load(m.group(1)) or {}
        prompt = m.group(2).strip()
        name = meta.get("name", path.stem)
        role = Role(
                    name=name,
                    description=meta.get("description", ""),
                    system_prompt=prompt,
                    model_alias=meta.get("model_alias", "default"),
                    skills=meta.get("skills", [])
                )
        roles[name] = role
    return roles



def _load_models(agents_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
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
    """Charge les défauts de l'orchestrateur, surchargés par le .agents/ du projet."""
    agents_dir = project_root / ".agents"

    skills = _load_skills(DEFAULTS / "skills")
    skills.update(_load_skills(agents_dir / "skills"))

    roles = _load_roles(DEFAULTS / "roles")
    roles.update(_load_roles(agents_dir / "agents"))

    context_file = agents_dir / "project.md"
    context = context_file.read_text(encoding="utf-8") if context_file.exists() else ""

    data = yaml.safe_load((agents_dir / "models.yaml").read_text(encoding="utf-8")) or {}

    for agent_name, agent_cfg in data.get("agents", {}).items():
            if agent_name in roles:
                role = roles[agent_name]
                role.model = agent_cfg.get("model") or role.model
                role.provider = agent_cfg.get("provider") or role.provider
                role.fallback = agent_cfg.get("fallback")
                role.num_ctx = agent_cfg.get("num_ctx")
                role.temperature = agent_cfg.get("temperature")
                role.timeout = agent_cfg.get("timeout")

    return Registry(
        roles=roles,
        skills=skills,
        context=context,
        aliases=data.get("aliases", {}),
        providers=data.get("providers", {}),
    )
