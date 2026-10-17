---
name: bluf
description: Writes a short-form message — Slack, email, PR comment, status update — that leads with the answer, conclusion, or ask in the first sentence. The body only exists to support that line. Make sure to use this skill whenever the user says "BLUF", "bottom line up front", "TL;DR", "lead with the answer", "get to the point", "tighten this", or pastes a message that buries the point in the third paragraph — even if they don't use those exact phrases.
---

# BLUF

Write a short-form message — chat, email, PR comment, status update — that puts the answer in the first sentence. Everything after only exists to support that line.

## Audience

A colleague reading on their phone between meetings. They will read the first sentence. They might read the second. They will *not* read paragraph three.

## When to use

Trigger on any of:
- "BLUF" / "bottom line up front" / "TL;DR" / "lead with the answer"
- "get to the point" / "tighten this" / "rewrite this so it doesn't bury the lede"
- The user pastes a message and the actual point is in the last sentence
- Any short-form written communication where attention is scarce: Slack, email, PR comment, standup note

For longer-form output with multiple supporting reasons — a proposal,
RFC, decision memo — use **minto-pyramid** instead. BLUF is the
opening sentence; Minto is the whole document.

## Output shape

Produce exactly this structure, in order:

1. **The line.** One sentence. The answer, the conclusion, the ask, or the status. Whatever the reader most needs to know if they read nothing else. Under 25 words.
2. **Why** (optional, 1–3 lines). Just enough to make the line defensible or actionable. Skip if the line stands alone.
3. **Detail** (optional, only if needed). Numbers, dates, links, names. Bullets, not paragraphs.

Total length: under 100 words for most messages. If you can't compress to 100, you have more than one BLUF — split it.

## Rules

**The line is the whole job.** If the rest of the message disappeared, the reader should still know what to do. Write the line, then ask: would this be enough?

**Lead with the verb that matters.** "Approved." "Shipped." "Blocked on X." "Need a decision by Friday." Status before story.

**No throat-clearing.** Skip "Hey just wanted to follow up on…", "Quick update on…", "I've been thinking about…". Start at the thing.

**Past tense for done, future tense for asks.** "Shipped the migration." / "Need your sign-off by EOD Thursday." Don't mix them in one line.

**One ask per message.** If you have two asks, send two messages or split them visibly. Buried second asks get ignored.

**Cut every adverb and softener.** "Just", "really", "quickly", "actually", "kind of" — gone. The line either stands or it doesn't.

## Anti-patterns

Do not:
- Open with "I hope this finds you well", "Quick question…", or any greeting that delays the point
- Use "circling back" / "looping in" / "just checking in" as the first line — the *substance* is the first line
- Hide the ask after three sentences of context
- Use the word "synergy", "leverage", or "circle back" anywhere
- Bullet-point a single idea — that's just a sentence with a dot in front
- End with "let me know your thoughts" — implied; cut it

## Calibration

Default length: 30–90 words.

For Slack: one line is often the whole message. Resist adding the "Why" unless it actually helps.

For email: the line is the first sentence of the body *and* the subject. Subjects like "Quick question" are banned — make the subject the line.

For PR comments: the line is the verdict (approve / request changes / question), then the specific reason. Don't make the reviewer hunt.

If the user gives you content to rewrite, preserve every fact — BLUF is restructuring, not deletion.

## Examples

**Good** (Slack message to your manager):

> Need 30 min today to talk through the auth migration — found a blocker that affects the Friday cutover.
>
> - Issue: the legacy provider's token TTL is shorter than we modelled
> - Impact: every active session would re-auth at cutover (~12k users)
> - Options: extend TTL on the legacy side (1-day eng cost), or stage the cutover by region

**Bad** (same message):

> Hey! Hope your morning is going well. So I've been working on the auth migration this week and I wanted to share some thoughts. As you know, we're planning to cut over on Friday. I was doing some testing yesterday and I noticed something interesting about the way the legacy provider handles token TTLs…

**Good** (PR comment):

> Approving with one nit: the retry helper should cap at 5 attempts, not 10 — we'll trip the upstream rate limit otherwise.

**Bad** (same):

> Thanks for putting this together! I had a chance to look through it this morning and overall it looks really solid. One small thing I noticed while reading through the retry helper — I was wondering if maybe we should think about…
