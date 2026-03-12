# Skill: Document Conversion

## Purpose
Convert, reformat, or transform documents and text between different formats.

## Supported Conversions
- Plain text / paragraphs → Markdown (headings, lists, bold, tables)
- Markdown → Plain text (strip all formatting)
- Unstructured notes → Structured Markdown document
- HTML snippets → Markdown
- JSON / YAML data → Markdown table
- Meeting notes / bullet points → formatted report
- Code snippets → fenced code blocks with correct language tag

## How to Use This Skill

### Step 1 — Identify the target format
Read what the user wants:
- "convert to md / markdown" → output Markdown
- "make it plain text" → strip all Markdown
- "format this as a report" → structured Markdown with headings
- "turn this into a table" → Markdown table

### Step 2 — Analyse the input
Before converting, identify:
- Are there logical sections? → use `##` headings
- Are there lists or steps? → use `-` bullets or `1.` numbered list
- Is there tabular data? → use `| col | col |` tables
- Is there code? → wrap in triple backticks with language tag
- Are there key terms to emphasise? → use `**bold**`

### Step 3 — Output rules
- Always start with a `# Title` derived from the content
- Preserve ALL information — never drop content during conversion
- Keep code exactly as-is, only add fencing
- For tables: align columns, include header separator row `|---|---|`
- If converting TO plain text: remove all `#`, `*`, `_`, backticks, `|`
- Add a blank line between every section

### Step 4 — Quality check (mental)
Before responding, verify:
- [ ] Nothing was lost from the original
- [ ] Headings are hierarchical (h1 → h2 → h3, never skip)
- [ ] Code blocks have a language tag
- [ ] Tables have a separator row

## Example

**Input:**
```
meeting notes 12 jan
attendees: alice bob charlie
we decided to use postgres
next steps: setup db, write migrations, deploy
```

**Output:**
```markdown
# Meeting Notes — 12 Jan

## Attendees
- Alice
- Bob
- Charlie

## Decisions
- Use PostgreSQL as the primary database

## Next Steps
1. Set up the database
2. Write migrations
3. Deploy
```