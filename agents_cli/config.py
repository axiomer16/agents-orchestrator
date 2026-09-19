from __future__ import annotations
from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel, Field, model_validator


class ProviderConfig(BaseModel):
    type: Literal["ollama", "bridge"] = "ollama"
    url: str | None = None  # ex: http://localhost:11434


class AgentModelConfig(BaseModel):
    provider: str
    model: str
    fallback: str | None = None  # "qwen3:14b" ou "ollama/qwen3:8b"
    temperature: float = 0.2
    num_ctx: int = 8192

    def fallback_parts(self) -> tuple[str, str] | None:
        """Retourne (provider, model) du fallback. Sans préfixe → même provider."""
        if not self.fallback:
            return None
        if "/" in self.fallback:
            prov, model = self.fallback.split("/", 1)
            return prov, model
        return self.provider, self.fallback


class ModelsConfig(BaseModel):
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    agents: dict[str, AgentModelConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_providers_exist(self) -> "ModelsConfig":
        for name, cfg in self.agents.items():
            if cfg.provider not in self.providers:
                raise ValueError(
                    f"Agent '{name}' utilise le provider inconnu '{cfg.provider}'"
                )
            fb = cfg.fallback_parts()
            if fb and fb[0] not in self.providers:
                raise ValueError(
                    f"Agent '{name}' : provider de fallback inconnu '{fb[0]}'"
                )
        return self

    @classmethod
    def load(cls, path: Path) -> "ModelsConfig":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)
