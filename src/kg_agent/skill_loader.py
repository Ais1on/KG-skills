from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import importlib.util
from typing import Any

import yaml


@dataclass(slots=True)
class SkillDefinition:
    name: str
    description: str
    path: Path
    markdown_path: Path
    body: str
    display_name: str = ""
    short_description: str = ""
    default_prompt: str = ""


@dataclass(slots=True)
class SkillInvokeResult:
    ok: bool
    skill: str
    output: Any
    error: str | None = None


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    if not content.startswith("---\n"):
        return {}, content
    marker = "\n---\n"
    end = content.find(marker, 4)
    if end == -1:
        return {}, content
    frontmatter = content[4:end]
    body = content[end + len(marker) :]
    meta = yaml.safe_load(frontmatter) or {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, body


def _read_agent_yaml(skill_dir: Path) -> dict[str, str]:
    agent_yaml = skill_dir / "agents" / "openai.yaml"
    if not agent_yaml.exists():
        return {}
    raw = yaml.safe_load(agent_yaml.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {}
    return {
        "display_name": str(raw.get("display_name", "")),
        "short_description": str(raw.get("short_description", "")),
        "default_prompt": str(raw.get("default_prompt", "")),
    }


def discover_skills(skills_dir: str | Path) -> dict[str, SkillDefinition]:
    root = Path(skills_dir)
    if not root.exists():
        return {}

    skill_map: dict[str, SkillDefinition] = {}
    for skill_dir in sorted(root.iterdir()):
        if not skill_dir.is_dir():
            continue

        markdown_path = skill_dir / "SKILL.md"
        if not markdown_path.exists():
            continue

        content = markdown_path.read_text(encoding="utf-8")
        frontmatter, body = _parse_frontmatter(content)
        agent_info = _read_agent_yaml(skill_dir)

        name = str(frontmatter.get("name") or skill_dir.name)
        description = str(frontmatter.get("description") or "")

        skill_map[name] = SkillDefinition(
            name=name,
            description=description,
            path=skill_dir,
            markdown_path=markdown_path,
            body=body.strip(),
            display_name=agent_info.get("display_name", ""),
            short_description=agent_info.get("short_description", ""),
            default_prompt=agent_info.get("default_prompt", ""),
        )

    return skill_map


def format_skill_catalog(skills: dict[str, SkillDefinition]) -> str:
    if not skills:
        return "No skills loaded."

    lines: list[str] = []
    for name in sorted(skills.keys()):
        item = skills[name]
        title = item.display_name or item.name
        summary = item.short_description or item.description or "No description"
        lines.append(f"- {item.name} ({title}): {summary}")
    return "\n".join(lines)


def _load_executor(skill: SkillDefinition):
    executor_path = skill.path / "executor.py"
    if not executor_path.exists():
        return None

    module_name = f"kg_skill_exec_{hashlib.md5(str(executor_path).encode('utf-8')).hexdigest()}"
    spec = importlib.util.spec_from_file_location(module_name, executor_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load executor for skill {skill.name}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, "run", None)
    if fn is None or not callable(fn):
        raise RuntimeError(f"Skill executor missing callable run(payload) in {executor_path}")
    return fn


def invoke_skill(skills: dict[str, SkillDefinition], skill_name: str, payload: dict[str, Any]) -> SkillInvokeResult:
    skill = skills.get(skill_name)
    if skill is None:
        return SkillInvokeResult(
            ok=False,
            skill=skill_name,
            output=None,
            error=f"Skill not found: {skill_name}",
        )

    try:
        runner = _load_executor(skill)
        if runner is None:
            return SkillInvokeResult(
                ok=True,
                skill=skill_name,
                output={
                    "mode": "spec_only",
                    "message": "No executor.py found, returning skill specification for manual execution.",
                    "skill": skill_name,
                    "description": skill.description,
                    "input": payload,
                    "spec": skill.body,
                },
            )

        result = runner(payload)
        return SkillInvokeResult(ok=True, skill=skill_name, output=result)
    except Exception as exc:  # pragma: no cover
        return SkillInvokeResult(
            ok=False,
            skill=skill_name,
            output=None,
            error=f"Skill execution failed: {exc}",
        )
