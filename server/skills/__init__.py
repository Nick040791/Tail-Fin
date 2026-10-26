"""Modular Skills Engine for Fin Assistant.

Discovers SKILL.md files under server/skills/<skill-name>/SKILL.md, parses YAML
frontmatter and Markdown instructions, and injects relevant skills into the
system prompt when triggered by user intent or slash commands.
"""

import os
import re

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))


def _parse_skill_md(path):
    """Parse YAML frontmatter and Markdown body from a SKILL.md file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        return None

    meta = {
        "name": os.path.basename(os.path.dirname(path)),
        "description": "",
        "triggers": [],
        "slash_command": "",
        "required_tools": [],
        "body": raw.strip(),
        "path": path,
    }
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1].strip()
            meta["body"] = parts[2].strip()
            for line in fm_text.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                k, _, v = line.partition(":")
                k = k.strip().lower()
                v = v.strip()
                if k == "name" and v:
                    meta["name"] = v.strip("'\"")
                elif k == "description" and v:
                    meta["description"] = v.strip("'\"")
                elif k == "slash_command" and v:
                    meta["slash_command"] = v.strip("'\"")
                elif k in ("triggers", "required_tools") and v.startswith("[") and v.endswith("]"):
                    items = [
                        item.strip().strip("'\"")
                        for item in v[1:-1].split(",")
                        if item.strip().strip("'\"")
                    ]
                    meta[k] = items
    return meta


def load_all_skills():
    """Return list of all discovered skill dicts sorted by name."""
    skills = []
    if not os.path.isdir(SKILLS_DIR):
        return skills
    for entry in sorted(os.listdir(SKILLS_DIR)):
        sub = os.path.join(SKILLS_DIR, entry)
        md_path = os.path.join(sub, "SKILL.md")
        if os.path.isdir(sub) and os.path.isfile(md_path):
            parsed = _parse_skill_md(md_path)
            if parsed:
                skills.append(parsed)
    return skills


def match_skills_for_prompt(user_text):
    """Return list of skills whose triggers or keywords match user_text."""
    if not user_text:
        return []
    lower = user_text.lower().strip()
    matched = []
    for sk in load_all_skills():
        if sk.get("slash_command") and lower.startswith(sk["slash_command"].lower()):
            matched.append(sk)
            continue
        for trig in sk.get("triggers", []):
            if trig.lower() in lower:
                matched.append(sk)
                break
    return matched


def format_skills_prompt_injection(user_text):
    """Build system prompt addendum for any active/matched skills."""
    matched = match_skills_for_prompt(user_text)
    if not matched:
        return ""
    blocks = ["\n\n### Active Assistant Skills"]
    for sk in matched[:2]:
        blocks.append(f"#### Skill: {sk['name']} — {sk['description']}\n{sk['body']}")
    return "\n\n".join(blocks)


def format_skills_list():
    """Format human-readable overview of all installed skills for /skills."""
    skills = load_all_skills()
    if not skills:
        return "No skills installed in server/skills/."
    lines = ["📚 Installed Fin Skills:"]
    for idx, sk in enumerate(skills, 1):
        cmd_str = f" ({sk['slash_command']})" if sk.get("slash_command") else ""
        trigs = ", ".join(sk.get("triggers", [])[:4])
        lines.append(
            f"[{idx}] {sk['name']}{cmd_str} — {sk['description']}\n"
            f"    Triggers: {trigs or 'manual'} | Tools: {', '.join(sk.get('required_tools', []))}"
        )
    return "\n".join(lines)
