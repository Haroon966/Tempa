"""Load vendored Rumi skills-pack context for Cursor SDK prompts.

Inject the router + skill map into the prompt so the agent has full Rumi
awareness without guessing. Secrets stay on disk (TOKENS.md / KEYS.md) — never
copied into the prompt or Slack.
"""

from __future__ import annotations

import re
from pathlib import Path

_FRONTMATTER_DESC_RE = re.compile(
    r"^---\s*\n(?:.*?\n)?description:\s*(.+?)\n",
    re.I | re.S,
)


def pack_root(cwd: str | Path) -> Path:
    return Path(cwd or "/repos/rumixtempa")


def _read_text(path: Path, *, limit: int = 120_000) -> str:
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) > limit:
        return text[: limit - 40] + "\n\n…_(truncated)_\n"
    return text


def _skill_description(skill_md: Path) -> str:
    raw = _read_text(skill_md, limit=4000)
    if not raw:
        return ""
    m = _FRONTMATTER_DESC_RE.match(raw)
    if m:
        return m.group(1).strip().strip("\"'")
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return ""


def skill_inventory(root: Path) -> str:
    skills = root / "skills"
    if not skills.is_dir():
        return "(skills/ missing)"
    lines: list[str] = []
    for folder in sorted(p for p in skills.iterdir() if p.is_dir()):
        skill_md = folder / "SKILL.md"
        if not skill_md.is_file():
            continue
        desc = _skill_description(skill_md) or "(see SKILL.md)"
        lines.append(f"- `{folder.name}` → skills/{folder.name}/SKILL.md — {desc}")
    return "\n".join(lines) if lines else "(no skills found)"


def load_rumi_pack_context(cwd: str | Path) -> str:
    """Full Rumi pack context for Cursor: router + AGENTS + skill map + paths."""
    root = pack_root(cwd)
    claude = _read_text(root / "CLAUDE.md")
    agents = _read_text(root / "AGENTS.md", limit=20_000)
    inventory = skill_inventory(root)
    parts = [
        "## Rumi pack root (cwd)",
        str(root.resolve() if root.exists() else root),
        "",
        "## CLAUDE.md (L1 router — authoritative task → skill map)",
        claude or "(CLAUDE.md missing — open skills/*/SKILL.md by name)",
        "",
        "## Skill inventory on disk",
        inventory,
        "",
        "## Credential files (read on disk; never print secret values)",
        f"- {root / 'TOKENS.md'}",
        f"- {root / 'KEYS.md'}",
        "Export needed env vars into the shell for scripts. Do NOT create a .env file.",
    ]
    if agents.strip():
        parts.extend(["", "## AGENTS.md", agents])
    return "\n".join(parts).strip()


def format_rumi_user_reply(agent_text: str) -> str:
    """Wrap Rumi's answer so the Slack user sees the full result and keeps control."""
    body = (agent_text or "").strip() or "_Rumi had nothing to add._"
    footer = (
        "\n\n---\n"
        "_Rumi (via Tempa). Reply in this thread to steer, refine, or undo — "
        "you have full control of the next step._"
    )
    if footer.strip() in body:
        return body
    return body + footer


def format_rumi_capability_reply(cwd: str | Path = "/repos/rumixtempa") -> str:
    """Immediate Slack answer for 'do you have rumi skills?' — from the vendored pack."""
    candidates = [
        pack_root(cwd),
        Path("/repos/rumixtempa"),
        # rumi_pack.py → slack → channels → tempa → src → repo root
        Path(__file__).resolve().parents[4] / "vendor" / "rumixtempa",
    ]
    root = next((p for p in candidates if (p / "skills").is_dir()), candidates[0])
    inventory = skill_inventory(root)
    if "(no skills" in inventory or "(skills/ missing)" in inventory:
        return (
            "Yes — Tempa is wired to the *Rumi* skills pack, but the pack isn’t mounted "
            "here yet (`/repos/rumixtempa`). After `docker compose up -d tempa-daemon`, "
            "ask again or say *use rumi to …* and I’ll run it for you."
        )
    lines: list[str] = []
    for raw in inventory.splitlines():
        m = re.match(r"^-\s+`([^`]+)`\s+→\s+.+\s+[—–\-]\s*(.+)$", raw.strip())
        if m:
            lines.append(f"• *{m.group(1)}* — {m.group(2).strip()}")
        elif raw.strip().startswith("- `"):
            name = raw.split("`")[1] if "`" in raw else raw.strip().lstrip("- ")
            lines.append(f"• *{name}*")
    body = "\n".join(lines) if lines else inventory
    return (
        "Yes — Tempa has the *Rumi* skills pack wired in. Ask me to *use rumi to …* "
        "and I’ll run the pack in the background.\n\n"
        f"*Available skills:*\n{body}\n\n"
        "Example: `use rumi to list my team’s Notion cards`\n\n"
        "---\n"
        "_Reply with a concrete ask to run one — you stay in control of the next step._"
    )
