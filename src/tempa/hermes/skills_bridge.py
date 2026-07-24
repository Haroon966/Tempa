from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ROUTING_POLICY = """---
name: slack-routing-policy
description: Permanent Slack teammate routing — product investigate vs QA vs Cursor
triggers:
  - check if
  - dashboard
  - product
  - scan
  - qa
  - deep review
  - github.com
workers: []
priority: 100
channels:
  - slack
  - dashboard
---

# Slack teammate routing (immutable policy)

- Phrases like "check if the count…", "teacher vanishes", "dashboard shows 128" are **product/data investigations**.
- They must **not** enqueue a lint/tests/security scan just because a product alias maps to a repo.
- **Rumi skills pack** is a hard route (`classify_rumi` + `rumi_pack` pre-hook): never answer from meeting archives / RAG.
- QA scans require **strong** intent (`scan`, `run qa`, `audit`, `deep review`) **or** an explicit `github.com` / `owner/repo` ref plus review/test wording.
- Product investigations with a known product/repo alias go to **Cursor jobs** (read or write), not `qa_scan_hook`.
- Coding write jobs: one short ack, then silence until the fix is ready. Never spam progress.
- Never post raw exceptions or `fatal:` git advice to Slack.
"""


def _hermes_dir() -> Path:
    from tempa.settings import get_settings

    path = get_settings().tempa_data_dir / "hermes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def skills_dir() -> Path:
    path = _hermes_dir() / "skills"
    path.mkdir(parents=True, exist_ok=True)
    return path


def learned_dir() -> Path:
    path = skills_dir() / "learned"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_seed_skills() -> None:
    """Sync Tempa config/skills into Hermes skills dir + seed routing policy."""
    dest_root = skills_dir()
    policy = dest_root / "slack-routing-policy"
    policy.mkdir(parents=True, exist_ok=True)
    skill_md = policy / "SKILL.md"
    if not skill_md.exists():
        skill_md.write_text(_ROUTING_POLICY, encoding="utf-8")

    from tempa.settings import get_settings

    src_root = get_settings().config_dir / "skills"
    if not src_root.is_dir():
        return
    for src in src_root.glob("*/SKILL.md"):
        name = src.parent.name
        target = dest_root / name
        target.mkdir(parents=True, exist_ok=True)
        target_md = target / "SKILL.md"
        try:
            if not target_md.exists() or src.stat().st_mtime > target_md.stat().st_mtime:
                shutil.copy2(src, target_md)
        except OSError as exc:
            logger.debug("skill sync skipped %s: %s", name, exc)


def format_active_skills_for_prompt(context: dict[str, Any] | None = None) -> str:
    ensure_seed_skills()
    from tempa.skills.matcher import match_skills
    from tempa.skills.prompt import format_skills_for_prompt

    # Prefer Hermes skills directory by temporarily extending config — load via paths
    blocks: list[str] = []
    for path in sorted(skills_dir().glob("*/SKILL.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        # Strip frontmatter for prompt body
        if text.startswith("---"):
            parts = text.split("---", 2)
            body = parts[2].strip() if len(parts) >= 3 else text
            name = path.parent.name
        else:
            body, name = text.strip(), path.parent.name
        blocks.append(f"### {name}\n{body[:1200]}")

    matched = match_skills(str((context or {}).get("user_message") or ""), context)
    matched_block = format_skills_for_prompt(matched)
    hermes_block = "\n\n".join(blocks[:8])
    return f"## Hermes skills\n{hermes_block}\n\n## Matched Tempa skills\n{matched_block}"


def record_plan_outcome(
    user_message: str,
    *,
    success: bool,
    notes: str = "",
    planned_steps: list[Any] | None = None,
) -> Path | None:
    """Persist a lightweight skill draft from a successful plan (learning loop)."""
    if not success:
        return None
    ensure_seed_skills()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = "".join(c if c.isalnum() else "-" for c in user_message.lower()[:40]).strip("-") or "plan"
    path = learned_dir() / f"{stamp}-{slug}.json"
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "user_message": user_message[:500],
        "notes": notes,
        "planned_steps": planned_steps or [],
        "success": success,
    }
    try:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.debug("record_plan_outcome failed: %s", exc)
        return None
    _curate_learned(max_keep=50)
    return path


def _curate_learned(*, max_keep: int = 50) -> None:
    """Curator-lite: keep newest learned skill drafts."""
    files = sorted(learned_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in files[max_keep:]:
        try:
            stale.unlink()
        except OSError:
            pass


def mirror_learned_to_config() -> int:
    """Optional: expose learned outcomes count for dashboard (no auto-write to config)."""
    return len(list(learned_dir().glob("*.json")))


def promote_learned_to_skills(*, limit: int = 5) -> list[Path]:
    """Turn recent successful plan traces into SKILL.md drafts under skills/learned/*/."""
    ensure_seed_skills()
    files = sorted(learned_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    written: list[Path] = []
    for path in files[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not data.get("success"):
            continue
        msg = str(data.get("user_message") or path.stem)[:80]
        slug = "".join(c if c.isalnum() else "-" for c in msg.lower()).strip("-")[:40] or "learned"
        dest = skills_dir() / "learned" / slug
        dest.mkdir(parents=True, exist_ok=True)
        steps = data.get("planned_steps") or []
        body = (
            f"---\nname: learned-{slug}\ndescription: Auto-learned from successful Tempa plan\n"
            f"triggers: []\nworkers: []\npriority: 10\n---\n\n"
            f"# Learned workflow\n\nOriginal request: {msg}\n\n"
            f"Notes: {data.get('notes')}\n\nSteps: {json.dumps(steps, ensure_ascii=False)[:800]}\n"
        )
        skill_path = dest / "SKILL.md"
        skill_path.write_text(body, encoding="utf-8")
        written.append(skill_path)
    return written
