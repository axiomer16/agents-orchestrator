from __future__ import annotations
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .agent_def import AgentDef, discover_agents
from .config import ModelsConfig
from .skill_def import Skill, discover_skills
from . import templates

AGENTS_DIR = ".agents"
GLOBAL_DIR = Path.home() / ".agents"   # ta bibliothèque perso


def find_workspace_root(start: Path | None = None) -> Path | None:
    """Remonte les dossiers parents jusqu'à trouver un .agents/."""
    cur = (start or Path.cwd()).resolve()
    for p in [cur, *cur.parents]:
        if (p / AGENTS_DIR).is_dir():
            return p
    return None


@dataclass
class Workspace:
    root: Path
    models: ModelsConfig
    agents: dict[str, AgentDef]
    skills: dict[str, Skill]
    warnings: list[str] = field(default_factory=list)

    @property
    def dir(self) -> Path:
        return self.root / AGENTS_DIR

    @classmethod
    def load(cls, root: Path) -> "Workspace":
        d = root / AGENTS_DIR
        models = ModelsConfig.load(d / "models.yaml")

        # Skills : globaux d'abord, le projet surcharge
        skills = discover_skills(GLOBAL_DIR / "skills", scope="global")
        skills.update(discover_skills(d / "skills", scope="project"))

        agents = discover_agents(d / "agents")

        ws = cls(root=root, models=models, agents=agents, skills=skills)
        ws._check_consistency()
        return ws

    def _check_consistency(self) -> None:
        known = set(self.skills)
        for name, agent in self.agents.items():
            if name not in self.models.agents:
                self.warnings.append(f"Agent '{name}' : aucun modèle dans models.yaml")
            for missing in agent.validate_skills(known):
                self.warnings.append(f"Agent '{name}' : skill introuvable '{missing}'")
        for name in self.models.agents:
            if name not in self.agents:
                self.warnings.append(f"models.yaml : agent '{name}' sans fichier agents/{name}.md")


def init_workspace(root: Path, force: bool = False) -> list[Path]:
    """Génère le squelette .agents/ ; copie les agents/skills globaux s'ils existent."""
    d = root / AGENTS_DIR
    created: list[Path] = []

    def write(rel: str, content: str) -> None:
        p = d / rel
        if p.exists() and not force:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        created.append(p)

    for sub in ("agents", "skills", "tasks/done", "logs"):
        (d / sub).mkdir(parents=True, exist_ok=True)

    write("project.md", templates.PROJECT_MD.format(project=root.name))
    write("architecture.md", templates.ARCHITECTURE_MD)
    write("models.yaml", templates.MODELS_YAML)
    write("tasks/queue.json", "[]\n")
    for name, content in templates.AGENTS.items():
        write(f"agents/{name}.md", content)
    for name, content in templates.SKILLS.items():
        write(f"skills/{name}/SKILL.md", content)

    # Surcharge par la bibliothèque globale (~/.agents/agents et ~/.agents/skills)
    for sub in ("agents", "skills"):
        src = GLOBAL_DIR / sub
        if src.is_dir():
            for item in src.iterdir():
                dst = d / sub / item.name
                if dst.exists() and not force:
                    continue
                if item.is_dir():
                    shutil.copytree(item, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dst)
                created.append(dst)

    return created
