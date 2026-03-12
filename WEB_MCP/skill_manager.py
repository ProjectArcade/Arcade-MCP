"""
skill_manager.py
────────────────
Loads skills from the ./skills/ folder and matches them to incoming queries.

Each skill file is a Markdown or text file named  <n>_skill.md
The first line should be  # Skill: <Human Readable Name>

Usage in server.py:
    from skill_manager import skill_manager, match_skill
    skill_text = match_skill(query)   # returns skill content or ""
"""

import os
import re
from pathlib import Path
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────
SKILLS_DIR = Path(__file__).parent / "skills"

# ── Skill definitions ─────────────────────────────────────────────────────────
# Each entry:  (skill_file_stem, [trigger_patterns])
# Patterns are matched case-insensitively against the user query.
# ORDER MATTERS — first match wins. Put more specific skills before generic ones.

SKILL_TRIGGERS: list[tuple[str, list[str]]] = [
    (
        "document_skill",
        [
            # ── dumnet / unscatter style ──
            r"\bdumnet\b",
            r"\bunscatter\b",
            r"\bdump\s+(?:to\s+)?(?:a\s+)?doc(?:ument)?\b",
            r"\bmake\s+(?:this\s+)?a\s+(?:clean\s+)?doc(?:ument)?\b",
            r"\bturn\s+(?:this\s+)?into\s+a\s+(?:clean\s+)?doc(?:ument)?\b",
            r"\bdocument\s+this\b",
            r"\bclean\s+(?:this\s+)?up\s+(?:and\s+)?(?:make|format|structure)\b",
            r"\borganis[e|z]e?\s+(?:this|these|my)\b",
            r"\bstructure\s+(?:this|these|my)\s+(?:notes?|text|data|info|content)\b",
            r"\bformat\s+(?:this|my)\s+(?:notes?|text|data|raw)\b",
            r"\bmake\s+(?:it|this)\s+readable\b",
            r"\bclean\s+up\s+my\s+notes?\b",
            r"\bformat\s+my\s+notes?\b",
            r"\bmake\s+sense\s+of\s+this\b",
            r"\binto\s+a\s+(?:clean\s+)?(?:markdown\s+)?doc(?:ument)?\b",
            # ── standard document/convert style ──
            r"\bconvert\b",
            r"\bto\s+(?:md|markdown|plain\s*text|txt|html)\b",
            r"\bformat\s+(?:this|as|into)\b",
            r"\breformat\b",
            r"\btransform\b.*\b(?:doc|text|file)\b",
            r"\bmake\s+(?:it\s+)?(?:markdown|md|plain)\b",
            r"\bmark\s*down\s+(?:version|format|this)\b",
            r"\binto\s+a\s+(?:table|report|document)\b",
            r"\bstructure\s+(?:this|these|my)\b",
            # ── pasted data triggers ──
            r"\bpasted?\b",
            r"\b(format|document)\s+(this|it|the|below|above)\b",
            r"\b(this|the)\s+(data|text|content|info|information)\b.*\b(format|document|clean)\b",
            r"\bbelow\b.*\b(format|document)\b",
            r"\bhere\s+is\b.*\b(format|document)\b",
        ],
    ),
    (
        "summary_skill",
        [
            r"\bsummar(?:ise|ize|y)\b",
            r"\btldr?\b",
            r"\btl;dr\b",
            r"\bgive\s+me\s+the\s+gist\b",
            r"\bkey\s+points?\b",
            r"\bmain\s+points?\b",
            r"\bshorten\s+(?:this|it)\b",
            r"\bcondense\b",
            r"\bin\s+brief\b",
            r"\bbrief\s+(?:overview|summary)\b",
            # ── pasted data triggers ──
            r"\bpasted?\b",
            r"\bclean\s+(?:this|it)\s+up\b",
            r"\b(summarize|summarise)\s+(this|it|the|below|above)\b",
            r"\b(this|the)\s+(data|text|content|info|information)\b.*\b(summar|clean)\b",
            r"\bbelow\b.*\bsummar\b",
            r"\bhere\s+is\b.*\bsummar\b",
        ],
    ),
    (
        "code_skill",
        [
            r"\bexplain\s+(?:this\s+)?code\b",
            r"\bwhat\s+does\s+(?:this|the)\s+code\b",
            r"\breview\s+(?:my\s+)?code\b",
            r"\bdebug\s+(?:this|my)\b",
            r"\bwhy\s+is\s+this\s+(?:failing|broken|not\s+working)\b",
            r"\bfix\s+(?:this|my)\s+(?:code|bug|error)\b",
            r"\badd\s+(?:comments|docstring|documentation)\b",
            r"\brefactor\b",
            r"\bwalk\s+me\s+through\s+(?:this\s+)?code\b",
        ],
    ),
]

# ── Loader ────────────────────────────────────────────────────────────────────
_skill_cache: dict[str, str] = {}


def load_skill(stem: str) -> str:
    """Load and cache a skill file by stem (e.g. 'document_skill')."""
    if stem in _skill_cache:
        return _skill_cache[stem]

    for ext in (".md", ".txt"):
        path = SKILLS_DIR / f"{stem}{ext}"
        if path.exists():
            content = path.read_text(encoding="utf-8")
            _skill_cache[stem] = content
            return content

    return ""  # skill file not found — fail silently


def match_skill(query: str) -> tuple[Optional[str], str]:
    """
    Check query against all skill triggers.

    Returns:
        (skill_name, skill_content)  — skill_name is human-readable title
        (None, "")                   — no skill matched
    """
    q = query.lower()
    for stem, patterns in SKILL_TRIGGERS:
        for pat in patterns:
            if re.search(pat, q, re.IGNORECASE):
                content = load_skill(stem)
                if content:
                    # Extract human-readable name from first line "# Skill: Name"
                    m = re.match(r"#\s*Skill:\s*(.+)", content.splitlines()[0])
                    name = m.group(1).strip() if m else stem
                    return name, content
    return None, ""


def list_skills() -> list[str]:
    """Return names of all available skill files."""
    if not SKILLS_DIR.exists():
        return []
    return [p.stem for p in SKILLS_DIR.iterdir() if p.suffix in (".md", ".txt")]