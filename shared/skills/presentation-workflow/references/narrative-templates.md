# Narrative templates

Templates for the three files Phase 1 writes: `deck/narrative.md`, `deck/outline.md` and
`deck/qa-and-rehearsal.md`. Keep the headings. The examples are fictional.

## Contents

1. Audience and occasion brief
2. Takeaway sentence
3. BLUF
4. Minto pyramid
5. Slide outline
6. Common arcs
7. Q&A bank
8. Rehearsal notes

---

## 1. Audience and occasion brief (top of `deck/narrative.md`)

```markdown
# <Deck working title> - narrative

Status: draft | approved   Decisions: <date - who approved what, and any changes>

## Audience
- Who: <roles, number of people, seniority>
- Decider in the room: <name or role>
- What they know now: <relevant background they already have>
- What they believe now: <the starting position you must move them from>
- What they care about: <the criteria they will judge by>
- What they fear: <the objection behind the objection>

## Occasion
- Setting: live in a room | call | recorded | read alone later
- Slot: <minutes total>, of which <minutes> for questions
- Working density: speaker deck | reading deck   (set here from the occasion; confirmed in Phase 2)
- Date: <date>   Template or brand: <file or "none">
```

## 2. Takeaway sentence

One sentence, subject and verb, that the audience could repeat to a colleague an hour later.

```markdown
## Takeaway
<Audience> should <conclude / decide / do> <specific thing>, because <the main reason>.
```

Example: "The leadership team should approve the Lisbon support hub this quarter, because it halves
response time at 30% lower cost than adding headcount in London."

Test: if it needs "and" between two conclusions, there are two talks. If it has no verb or no
ask, it is a topic.

## 3. BLUF

```markdown
## BLUF
**Answer:** <the recommendation, finding or decision, in one sentence>
**Ask:** <what you need from the audience, by when>
**Why it matters:** <the cost of not acting, or the size of the gain, with a number>
**Confidence and risks:** <how sure you are, and the one thing that could change the answer>
```

The BLUF becomes the first slide's headline and the opening ninety seconds of the talk.

## 4. Minto pyramid

```markdown
## Pyramid
**Answer (apex):** <same claim as the takeaway>

1. **Reason A (a claim, not a topic):** <sentence>
   - Evidence: <number, example or source>
   - Evidence: <number, example or source>
2. **Reason B:** <sentence>
   - Evidence: <...>
3. **Reason C:** <sentence>
   - Evidence: <...>

**Objection and answer:** <the strongest counter-argument and the reply>
**MECE check:** <do A, B and C overlap? is there a gap a critic would name?>
```

Two to four reasons; three is the sweet spot. "Cost" is a topic; "The hub pays for itself in nine
months" is a claim. Number beats adjective.

## 5. Slide outline (`deck/outline.md`)

The file the build phase receives. Start with the Phase 2 decision block, then the table of
headlines, then one block per slide.

```markdown
# <Deck working title> - outline

## Format decision (Phase 2)
- Format: .pptx | HTML | undecided     Built with: <skill>
- Density: speaker deck | reading deck   (working value from Phase 1; if it changes here, revise the outline and re-approve it first)
- Length: <N> slides for <M> minutes
- Template or style: <file, brand rules, mood words>
- Output path: `deck/<slug>.pptx` or `deck/<slug>.html`

## Headline list (read these alone: they tell the story)
| # | Headline (the takeaway, with a verb) | Section |
| --- | --- | --- |
| 1 | We should open the Lisbon support hub this quarter | Answer |
| 2 | Response time is the churn driver, and it is getting worse | Reason A |
| 3 | A hub halves response time at 30% lower cost than hiring in London | Reason B |
| 4 | Payback takes nine months and the downside is capped | Reason C |
| 5 | We need sign-off today to hire before September | Ask |

## Slides

### Slide 1 - We should open the Lisbon support hub this quarter
- Idea: the recommendation and the ask, up front.
- Shows: the headline, the three numbers (response time, cost, payback), no other content.
- Notes (said aloud): "I will recommend one thing today and ask for one decision ..."
- Source: `finance/hub-model.xlsx`, sheet "Summary".

### Slide 2 - <next headline>
- Idea: <exactly one>
- Shows: <chart, image, diagram or up to three bullets; name the data>
- Notes (said aloud): <the spoken version, including the transition to slide 3>
- Source: <file, link or "[needed: who provides it]">

## Appendix (optional)
- A1 - <headline> - backs Q&A item <n>
```

Rules: slide 1 states the answer; one reason per middle slide; the last slide is the ask; every
figure has a source or a `[needed: ...]` marker; headlines use verbs.

## 6. Common arcs

| Occasion | Arc (one slide or a short run each) |
| --- | --- |
| Decision to a leadership group | Answer and ask, situation in one slide, options considered, recommendation reasons A-C, risks and mitigations, cost and timeline, ask |
| Status or board update | Overall status and the one thing needing attention, results against plan, what changed since last time, risks, next period, asks |
| Pitch to investors or customers | Problem the audience feels, why now, the solution in action, evidence it works, market, model, team, ask |
| Teaching or conference talk | Promise (what you will be able to do), the problem, three ideas each with a demo or example, the combined takeaway, next step |
| Post-mortem or incident review | What happened and the impact, timeline, root cause, what worked, what we change, owners and dates |

Adapt the arc to the pyramid; never fill a slot only because the arc has one.

## 7. Q&A bank (`deck/qa-and-rehearsal.md`)

```markdown
# Q&A bank

| # | Likely question | Asked by (role) | Short answer (two sentences) | Backing slide or appendix | Confidence |
| --- | --- | --- | --- | --- | --- |
| 1 | What if hiring in Lisbon takes longer than planned? | Finance | Each month of delay costs about <number>; the plan has a three-month buffer. | A2 | high |

## Questions we cannot answer yet
- <question> - owner: <name> - needed by: <date>
```

Include the hardest five to ten questions, the ones the audience fears asking, and the one the
presenter hopes nobody asks.

## 8. Rehearsal notes

```markdown
# Rehearsal notes

- Opening line (say it first, from memory): "<...>"
- Timing: Answer 3 min | Reason A 5 min | Reason B 5 min | Reason C 4 min | Ask 1 min | Questions 12 min
- Transitions: 2 to 3 - "<line>"; 4 to 5 - "<line>"
- If time shrinks to <N> minutes, cut: <slides>, keep: <slides>
- Hard moments: <slide and what makes it hard, how to handle it>
- Equipment and room: <clicker, adapter, backup PDF, offline copy>
- Closing line: "<the ask, restated>"
```
