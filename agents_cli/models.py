from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    content: str
    source: Path

    @classmethod
    def from_file(cls, path: Path) -> Skill:
        text = path.read_text(encoding="utf-8")
        meta: dict[str, str] = {}
        body = text
        if text.startswith("---"):
            _, header, body = text.split("---", 2)
            for line in header.strip().splitlines():
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip()
        return cls(
            name=meta.get("name", path.parent.name),
            description=meta.get("description", ""),
            content=body.strip(),
            source=path,
        )


@dataclass
class Role:
    name: str
    description: str
    system_prompt: str
    model_alias: str = "default"
    skills: list[str] = field(default_factory=list)
    model: str | None = None
    provider: str | None = None
    fallback: str | None = None
    num_ctx: int | None = None
    temperature: float | None = None
    timeout: int | None = None

    def build_prompt(
        self,
        skills: dict[str, Skill],
        project_context: str = "",
    ) -> str:
        parts = [self.system_prompt.strip()]
        if project_context:
            parts.append("# Contexte du projet\n" + project_context.strip())
        for name in self.skills:
            skill = skills.get(name)
            if skill is None:
                for name in self.skills:
                    skill = skills.get(name)
                    if skill is None:
                        parts.append(f"# Skill manquant : {name} (ignoré)")
                        continue
                    parts.append(f"# Skill : {skill.name}\n{skill.content}")
        return "\n\n".join(parts)
