from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lord_of_the_machines.llm import BaseAgent
from lord_of_the_machines.mission.prompting import (
    RolePromptProfile,
    compose_system_prompt,
    default_role_profile,
)


@dataclass(slots=True)
class RoleAgentFactoryConfig:
    config_path: str | Path | None = None
    include_golden_rules: bool = True
    base_overrides: dict[str, Any] = field(default_factory=dict)
    role_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    role_profile_overrides: dict[str, RolePromptProfile] = field(default_factory=dict)
    extra_dna_rulesets_by_role: dict[str, tuple[str, ...]] = field(default_factory=dict)


class RoleAgentFactory:
    def __init__(self, *, config: RoleAgentFactoryConfig | None = None) -> None:
        self.config = config or RoleAgentFactoryConfig()

    def create(
        self,
        role_name: str,
        *,
        client: Any | None = None,
        rate_limiter: Any | None = None,
        **overrides: Any,
    ) -> BaseAgent:
        profile = self.config.role_profile_overrides.get(role_name) or default_role_profile(role_name)
        system_prompt = compose_system_prompt(
            profile,
            include_golden_rules=self.config.include_golden_rules,
            extra_rulesets=self.config.extra_dna_rulesets_by_role.get(role_name, ()),
        )
        merged_overrides = {
            **self.config.base_overrides,
            **self.config.role_overrides.get(role_name, {}),
            **overrides,
            "system_prompt": system_prompt,
        }

        kwargs: dict[str, Any] = {}
        if client is not None:
            kwargs["client"] = client
        if rate_limiter is not None:
            kwargs["rate_limiter"] = rate_limiter
        return BaseAgent.new(self.config.config_path, **kwargs, **merged_overrides)
