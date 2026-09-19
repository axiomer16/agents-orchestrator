from __future__ import annotations
from pathlib import Path
import frontmatter
from pydantic import BaseModel, Field


class AgentDef(BaseModel):
    name: str
    role: str = ""
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    max_retries: int = 3
    timeout: int = 300           # secondes
    output_format: str = "json"  # "json" | "text"
    system_prompt: str = Field(repr=False)
    path: Path

    @classmethod
    def load(cls, agent_md: Path) -> "AgentDef":
        post = frontmatter.load(agent_md)
        meta = dict(post.metadata)
        meta.setdefault("name", agent_md.stem)
        return cls(system_prompt=post.content, path=agent_md, **meta)

    def validate_skills(self, known: set[str]) -> list[str]:
        """Retourne les skills référencés mais introuvables."""
        return [s for s in self.skills if s not in known]


def discover_agents(agents_dir: Path) -> dict[str, AgentDef]:
    found: dict[str, AgentDef] = {}
    if not agents_dir.is_dir():
        return found
    for md in sorted(agents_dir.glob("*.md")):
        agent = AgentDef.load(md)
        found[agent.name] = agent
    return found
