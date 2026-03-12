# Skill: Code Explanation & Review

## Purpose
Explain, review, debug, or document code snippets pasted by the user.

## Trigger phrases
- "explain this code", "what does this do", "walk me through"
- "review my code", "is this good", "any issues"
- "debug this", "why is this failing", "fix this"
- "add comments", "document this", "write docstring"
- "refactor", "optimise", "make this cleaner"

## Response modes

### EXPLAIN mode
Use when: user asks "what does this do" or "explain"
Structure:
1. **One-line summary** — what the code does overall
2. **Line-by-line or block-by-block walkthrough** — use inline comments style
3. **Key concepts used** — name patterns, algorithms, APIs
4. **Gotchas** — anything surprising or non-obvious

### REVIEW mode
Use when: user asks "review", "is this good", "any issues"
Structure:
1. **Overall assessment** (1-2 sentences)
2. **Issues found** (bugs, edge cases, security, performance) — use ❌
3. **Suggestions** — use 💡
4. **What's done well** — use ✅

### DEBUG mode
Use when: user pastes an error or says "fix this"
Structure:
1. **Root cause** — explain WHY it fails
2. **Fixed code** — always show the corrected version in a code block
3. **What changed** — bullet list of changes made

### DOCUMENT mode
Use when: user asks for comments, docstrings, or docs
- Add docstring at function/class level
- Inline comments only for non-obvious logic (not every line)
- Follow the language's convention (Python: Google style docstrings, JS: JSDoc)

## Rules
- Always use fenced code blocks with the correct language tag
- When fixing code, show the FULL corrected version, not just the changed lines
- Never silently change logic — if you change behaviour, say so explicitly
- If code is in a language you're uncertain about, say so