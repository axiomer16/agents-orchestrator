from __future__ import annotations
from pathlib import Path
import frontmatter
from pydantic import BaseModel, Field


class Skill(BaseModel):
    name: str
    description: str
    path: Path
    body: str = Field(repr=False)  # contenu complet, chargé à la demande
    scope: str = "project"        # "project" ou "global"

    def summary(self) -> str:
        """Ligne courte injectée dans le prompt (progressive disclosure)."""
        return f"- {self.name}: {self.description}"

    @classmethod
    def load(cls, skill_md: Path, scope: str = "project") -> "Skill":
        post = frontmatter.load(skill_md)
        meta = post.metadata
        name = meta.get("name") or skill_md.parent.name
        if "description" not in meta:
            raise ValueError(f"{skill_md}: frontmatter sans 'description'")
        return cls(
            name=name,
            description=meta["description"],
            path=skill_md,
            body=post.content,
            scope=scope,
        )


def discover_skills(skills_dir: Path, scope: str = "project") -> dict[str, Skill]:
    """Charge tous les skills/*/SKILL.md d'un dossier."""
    found: dict[str, Skill] = {}
    if not skills_dir.is_dir():
        return found
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        skill = Skill.load(skill_md, scope=scope)
        found[skill.name] = skill
    return found
