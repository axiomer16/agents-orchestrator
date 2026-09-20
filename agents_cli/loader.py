from __future__ import annotations
from pathlib import Path
import yaml
from agents_cli.models import Role, Skill
from dataclasses import dataclass, fields


DEFAULTS = Path(__file__).parent


def _load_skills(directory: Path) -> dict[str, Skill]:
    if not directory.exists():
        return {}
    return {
        skill.name: skill
        for skill in (Skill.from_file(p) for p in directory.glob("*/SKILL.md"))
    }


def _load_roles(directory: Path) -> dict[str, Role]:
    if not directory.exists():
        return {}
    known = {f.name for f in fields(Role)}
    roles: dict[str, Role] = {}
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        # compat : ancien champ "model" -> "model_alias"
        if "model" in data and "model_alias" not in data:
            data["model_alias"] = data.pop("model")
        unknown = set(data) - known
        if unknown:
            msg = f"{path.name} : champs inconnus {sorted(unknown)}"
            raise ValueError(msg)
        roles[data["name"]] = Role(**data)
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
        entry = self.aliases.get(role.model_alias)
        if entry is None:
            return f"[alias absent: {role.model_alias}]", "-"
        return entry.get("model", "?"), entry.get("provider", "ollama")


def load_registry(project_root: Path) -> Registry:
    """Charge les défauts de l'orchestrateur, surchargés par le .agents/ du projet."""
    agents_dir = project_root / ".agents"

    skills = _load_skills(DEFAULTS / "skills")
    skills.update(_load_skills(agents_dir / "skills"))

    roles = _load_roles(DEFAULTS / "roles")
    roles.update(_load_roles(agents_dir / "roles"))

    context_file = agents_dir / "project.md"
    context = context_file.read_text(encoding="utf-8") if context_file.exists() else ""

    data = yaml.safe_load((agents_dir / "models.yaml").read_text(encoding="utf-8")) or {}
    return Registry(
        roles=roles,
        skills=skills,
        context=context,
        aliases=data.get("aliases", {}),
        providers=data.get("providers", {}),
    )
