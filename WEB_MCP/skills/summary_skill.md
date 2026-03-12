# Skill: Summarisation

## Purpose
Summarise long text, articles, documents, or conversation history into concise output.

## Trigger phrases
- "summarise", "summarize", "tldr", "tl;dr", "give me the gist"
- "shorten this", "make it shorter", "condense"
- "key points", "main points", "bullet summary"
- "in brief", "brief overview", "quick summary"

## Summary types & when to use them

| Type | When | Format |
|---|---|---|
| **One-liner** | User says "one sentence" or "in a nutshell" | Single sentence |
| **Bullet summary** | Default for most requests | 3-7 bullet points |
| **Executive summary** | Long docs, reports, articles | 1 para + bullets |
| **Section-by-section** | Structured docs with headings | Mirror original headings |

## Rules
1. **Never add information** not present in the original
2. **Preserve numbers, names, dates** exactly — never paraphrase figures
3. **Shortest first** — lead with the most important point
4. Bullets should be **one idea each**, max 15 words per bullet
5. If the original has a conclusion, surface it prominently
6. Use the user's language (if they wrote in Hindi, summarise in Hindi unless asked otherwise)

## Format template (bullet summary)

```
**Summary**

- [Most important point]
- [Second point]
- [Third point]
...

**Key takeaway:** [One sentence conclusion]
```

## Example

**Input:** *(long article about climate change)*

**Output:**
```
**Summary**

- Global temperatures have risen 1.1°C above pre-industrial levels
- Extreme weather events increased 5× since 1970
- Renewable energy now cheaper than fossil fuels in 90% of markets
- 2030 emissions targets are being missed by most G20 nations

**Key takeaway:** Climate change is accelerating but renewable solutions are now economically viable.
```