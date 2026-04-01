from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..config import AgentConfig
from ..app_state import AGENT_STORE
from ..services import config_to_dict, skill_names
from ..loaders.skill_loader import discover_skills

router = APIRouter()


@router.get("/api/defaults")
def get_defaults() -> dict[str, Any]:
    config = AgentConfig()
    return {
        "config": config_to_dict(config),
        "skills": skill_names(config),
        "agents_count": len(AGENT_STORE),
    }


@router.get("/api/skills")
def get_skills(skills_dir: str = "skills") -> dict[str, Any]:
    skill_map = discover_skills(skills_dir)
    records: list[dict[str, Any]] = []
    for item in skill_map.values():
        records.append(
            {
                "name": item.name,
                "display_name": item.display_name,
                "description": item.description,
                "short_description": item.short_description,
                "default_prompt": item.default_prompt,
            }
        )
    records.sort(key=lambda item: item["name"])
    return {"skills_dir": skills_dir, "skills": records, "count": len(records)}
