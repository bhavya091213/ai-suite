---
name: exec-summary
description: Explains a topic, decision, incident, or proposal to a busy decision-maker who has 60 seconds. Leads with the call to make or the outcome, not the mechanism. Make sure to use this skill whenever the user says "exec summary", "executive summary", "TL;DR for my boss", "for leadership", "for the VP", "summarize for stakeholders", "one-pager", "elevator pitch", or asks to summarize something for a non-technical or time-constrained audience — even if they don't use those exact phrases.
---

# Exec Summary

Explain a topic, decision, incident, or proposal to a busy decision-maker so they can act on it in 60 seconds.

## Audience

A senior leader who is smart, not in the weeds, and has eight other things to read today. They want to know: *what do I do with this?* not *how does it work?*

## When to use

Trigger on any of:
- "exec summary" / "executive summary" / "summary for leadership"
- "TL;DR for my boss" / "for the VP" / "for the board"
- "summarize for stakeholders" / "one-pager" / "elevator pitch"
- Any request to compress a complex topic for a busy, non-technical, or decision-making audience

## Output shape

Produce exactly this structure, in order:

1. **The bottom line.** One sentence. Lead with the decision, the outcome, or the ask. If they read nothing else, this is the line that matters.
2. **Why it matters.** One sentence. Tie it to revenue, risk, time, cost, or strategy — the things a leader actually tracks.
3. **What you need from them.** One short line. A decision, a sign-off, a budget, an introduction, or "FYI, no action needed." Be explicit.
4. **Context** (3–5 bullets). Just enough background to make the bottom line defensible. Numbers over adjectives. Dates over "recently."
5. **Options or next steps** (2–3 bullets). Each option in one line, with the trade-off named. No paragraphs.

Total length: **under 200 words.** If you can't compress it, the thinking isn't done yet.

## Rules

**Lead with the ask, not the journey.** Don't explain how you got there before saying what you decided. They'll ask if they want the journey.

**Numbers, not adjectives.** "Reduced p95 latency from 1.2s to 340ms" beats "significantly improved performance." If you don't have a number, name a date or a count.

**One option recommended.** If you list options, mark one as the recommendation. Leaders hate menus without an entrée.

**Cut every adverb.** "Very", "really", "extremely", "quite", "significantly" all get deleted. The number does the work.

**No process narration.** Skip "we met with the team and discussed the approach, then…". Start with the conclusion.

**Active voice.** "We shipped X" not "X was shipped." "Recommend approving" not "It is recommended that approval be granted."

## Anti-patterns

Do not:
- Open with background, history, or "as you may recall…"
- Use bullet lists of 7+ items — that's a memo, not a summary
- Include charts or diagrams in the summary itself (link them, don't embed)
- Hedge ("might", "could potentially", "in some cases") more than once
- Define internal jargon — if a leader uses the term in meetings, you can use it. If not, replace it.
- End with "let me know if you have questions" — implied, redundant

## Calibration

Default length: 120–180 words.

If the topic is genuinely a yes/no decision, the summary can be 3 lines: bottom line, why, ask.

If the user is summarizing *for themselves* (e.g., "give me a TL;DR of this article"), drop the "what you need from them" line — there's no audience to act.

If the audience is technical leadership (CTO, staff eng), you can keep one or two precise technical terms. For non-technical leadership (CEO, board, sales VP), translate every term.

## Examples

**Good** (incident summary for VP Eng):

> **Bottom line:** Payments were down for 47 minutes on Tuesday; root cause identified and fixed. Recommend approving the $40k spend to prevent the same class of failure.
>
> **Why it matters:** Estimated revenue impact $180k. Same failure mode is currently possible in checkout and refunds.
>
> **What I need from you:** Sign-off on the $40k engineering spend (one sprint, 2 engineers).
>
> **Context:**
> - Outage: 14:03–14:50 UTC, Tuesday
> - Cause: DB connection pool exhaustion under a retry storm
> - Detection: 4 minutes (alerts fired correctly)
> - Resolution: manual restart; permanent fix scoped
>
> **Options:**
> - **Recommended:** Sprint-scoped fix ($40k, 2 weeks, prevents recurrence)
> - Defer: cheaper now, but next incident likely within a quarter

**Bad** (same incident):

> So on Tuesday afternoon we had a really significant incident with the payments system. It started around 2pm UTC when our monitoring detected elevated latencies. The on-call engineer was paged and began investigating. After some digging, we discovered that the connection pool had been exhausted due to a cascading retry pattern from the upstream service. This is actually a pretty common failure mode in distributed systems, and there are a number of ways we could potentially address it…
