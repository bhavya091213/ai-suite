---
name: minto-pyramid
description: Structures a longer-form argument, proposal, or decision document using Barbara Minto's pyramid principle — the answer at the top, two to four MECE supporting reasons under it, and detail under each reason. Make sure to use this skill whenever the user says "Minto", "pyramid principle", "structure this proposal", "structure this argument", "make this argument tighter", "this doc rambles", or asks for help organising a recommendation, proposal, or decision doc that has more than one supporting reason — even if they don't use those exact phrases.
---

# Minto Pyramid

Structure a longer-form argument — proposal, recommendation, decision doc, strategy memo — so the reader can follow the logic top-down and stop at any level.

## Audience

A reader who needs to *evaluate* an argument, not just read a message. They want to know what you're recommending and whether the reasoning holds up. They will read the top of every section. They will read the detail only where they want to push back.

## When to use

Trigger on any of:
- "Minto" / "pyramid principle" / "structure this in a pyramid"
- "structure this proposal" / "structure this argument" / "tighten this argument"
- "this doc rambles" / "rewrite this top-down" / "lead with the recommendation"
- Any longer-form output — proposal, RFC, recommendation, decision memo, strategy doc — with more than one supporting reason

For short-form messages where one opening sentence carries the
answer — chat, email, comment threads — use **bluf** instead. BLUF
is the lede; Minto is the whole pyramid.

## Output shape

Produce exactly this structure, in order:

1. **The answer** (1–2 sentences). The recommendation, decision, or main conclusion. Stated as a claim, not a question. This is the apex of the pyramid.
2. **The supporting reasons** (2–4 grouped points). Each is a single sentence that itself reads like a claim. Together they must be MECE — mutually exclusive, collectively exhaustive — so the reader feels they have the whole argument once they've read these three or four lines.
3. **Detail under each reason** (a short paragraph or 2–4 bullets per reason). Evidence, numbers, mechanism, caveat. Just enough that a sceptic could stop here and either agree or formulate a specific objection.
4. **What this changes** (optional, 1–2 sentences). The decision, action, or implication that follows if the argument holds. Skip if the answer in step 1 is itself the action.

A reader who reads only step 1 should know what you're proposing. A reader who reads steps 1–2 should know *why*. A reader who reads everything should be able to push back at the specific point of disagreement.

## Rules

**Answer first, every time.** Never open with background, problem statement, or "as you may recall." The pyramid is upside-down compared to a narrative — start at the top.

**Reasons must be MECE.** If two of your reasons overlap, merge them. If together they leave a gap a critic could drive a truck through, add the missing one. Three reasons is the sweet spot; two is fine; five is a sign the grouping is wrong.

**Each reason is a claim, not a topic.** "Cost" is a topic. "The migration pays for itself within 9 months" is a claim. Always the second form.

**Pyramid at every level.** Inside each reason's detail, lead with the sub-claim, then evidence. The structure is recursive.

**Numbers over adjectives.** A claim with a number is testable. A claim with "significant" is rhetoric.

**One pyramid per doc.** If you have two answers, you have two documents. Don't braid them.

## Anti-patterns

Do not:
- Open with "Background", "Context", or a timeline of what led to this
- Use generic group labels like "Pros", "Cons", "Considerations" — those aren't claims, they're buckets
- List five or more reasons — that's an unstructured list, not a pyramid
- Mix levels (a top-level "reason" that's actually a sub-point of another reason)
- Hedge the top claim ("It might be worth considering whether…") — the apex must be a position, not a musing
- Hide the recommendation behind options — present options *under* a recommended one, not instead of one

## Calibration

Default length: 300–800 words. Anything shorter is probably a BLUF; anything longer is probably hiding a missing claim.

For 2-page memos: keep step 3 (detail) to 2–3 sentences per reason. Link out for evidence; don't embed.

For RFCs and longer strategy docs: step 3 can become full sections, each itself pyramid-structured.

If the user gives you a rambling existing doc, preserve every fact — restructure, don't summarise. The job is to make the *same content* readable top-down.

If the underlying argument doesn't actually hold (you can find no MECE grouping of reasons), say so. Don't force a pyramid onto bad reasoning — flag the gap instead.

## Examples

**Good** (a recommendation memo):

> **Recommendation:** Replace the in-house job queue with SQS over the next quarter.
>
> **Why:**
> - The current queue is the top driver of on-call pages (38% of incidents in Q1) — every fix has been a patch, not a root cause.
> - SQS removes the entire class of failure at a marginal cost of ~$400/month, well under one engineer-hour.
> - The migration is bounded: 4 producers, 2 consumers, no exotic semantics — estimated at one engineer for three weeks.
>
> **Detail:**
> - *On-call cost:* see oncall-q1 dashboard; 14 of 37 pages were queue-related, average MTTR 42 minutes.
> - *Cost model:* current self-hosted cluster is $1,100/month plus operational toil; SQS estimate based on Q1 message volume × 1.5x buffer.
> - *Scope:* migration plan and risk register linked. Only non-trivial wrinkle is the priority queue for refunds — SQS doesn't support it natively, mitigated with a separate FIFO queue.
>
> **What this changes:** Approval unblocks the Q3 plan; without it the on-call rotation needs a second engineer to stay sustainable.

**Bad** (same recommendation):

> Over the past few quarters we've been seeing an increasing number of incidents related to our job queue infrastructure. The team has been working hard to address these, but it's become clear that we may need to consider a more structural change. There are several factors at play here. First, the on-call load has been growing. Second, the operational costs are non-trivial. Third…
