---
name: presentation-workflow
description: Four-phase, gated workflow that builds the story before the slides - audience, one-sentence takeaway, BLUF, Minto pyramid, a slide outline with one idea per slide and takeaway headlines, a Q&A bank and rehearsal notes - then picks the format (editable .pptx or HTML deck, speaker deck or reading deck), builds the deck with the matching skill, QA-checks the rendered slides and hands back file paths. Use when the user says "make a deck", "presentation", "slides", "pitch deck", "board update deck", "conference talk", or wants a presentation planned before it is designed.
origin: local
---

# Presentation workflow

Narrative first, deck second. Most bad decks are a good-looking pile of topics with no argument;
this workflow fixes the argument before a single slide exists, then hands a finished outline to
whichever deck-building skill the format calls for. The user owns the message (what the audience
should conclude and do) and the format; you own the structure, the build and the checking. The
workflow reads the same in Claude Code and Codex; where a host tool matters, both are named.

Four rules that never bend:

1. **Story before slides.** No slide is built until the user has approved the narrative and the
   outline. The build phase receives the outline file and never re-derives the story; a change of
   argument goes back through the gate.
2. **One idea per slide, and the headline is the takeaway.** A headline is a sentence with a verb
   that states what the audience should conclude ("Q4 revenue beat plan by 8%, driven by APAC"),
   never the topic ("Q4 results"). Two arguments on a slide mean two slides.
3. **Honesty.** Never invent numbers, quotes, customer names, logos or sources; mark a missing
   figure `[needed: <what, from whom>]` in the outline and in the deck. Never say a deck was
   rendered, checked or opened unless this session rendered, checked or opened it; write "not
   rendered" or "not run" instead of "verified".
4. **Never delete.** Never run `rm` / `rm -rf`, directly or via a subagent. Relocate with `mv`
   instead. If something must be retired, `mv` it into a backup location (e.g.
   `~/.agents/backups/retired-<what>/`) and say so in the report.

Helpers beside this file: `references/narrative-templates.md` (audience brief, BLUF, Minto
pyramid, slide outline, Q&A bank and rehearsal notes templates) and
`references/deck-qa-checklist.md` (the Phase 4 checks and how to render).

## Phases

| Phase | Output | Gate |
| --- | --- | --- |
| 1 Story | `deck/narrative.md`, `deck/outline.md`, `deck/qa-and-rehearsal.md` | User approves narrative, outline and working density |
| 2 Format | Format, confirmed density and template recorded at the top of `deck/outline.md` | User confirms format and density; a density change reopens the Phase 1 gate |
| 3 Build | The deck file (`.pptx` or `.html`) with speaker notes | none |
| 4 QA | Rendered-slide review, fixes, QA summary | none |

After a context compaction, re-read the three `deck/` files instead of re-deriving them.

## Phase 1: story

Read before asking: any draft, notes, data files, earlier decks, the calendar invite or brief the
user points at, and the audience's prior material. Do not ask for anything that can be read. Then
ask, in one or two rounds (bounded choices through the host's question tool, `AskUserQuestion` in
Claude Code; plain questions otherwise):

- **Audience**: who exactly, how many, how senior, what they already know and believe, what they
  fear or want, and who in the room decides.
- **Occasion**: live in a room, a call, a recorded talk, or read alone later; the time slot and
  how much of it is questions. The answer sets the working density: presented to an audience means
  a speaker deck, read alone later means a reading deck (differences in the Phase 2 table). If the
  deck must serve both, ask which one it is built for.
- **Takeaway and ask**: what should they conclude, and what should they do afterwards.
- **Evidence**: the numbers, examples and sources that exist, and what is missing.
- **Constraints**: a template or brand, a required length, things that must not be said.

Then write, in this order (templates in `references/narrative-templates.md`):

1. **Takeaway**: one sentence the audience should leave with. If it needs "and", there are two
   talks; pick one.
2. **BLUF**: the answer, the ask and the deadline in the first lines. Use `bluf` when installed.
3. **Pyramid**: the answer on top, two to four MECE supporting reasons as claims (not topics),
   evidence under each. Use `minto-pyramid` when installed. Order reasons strongest first when the
   audience is senior or short on time, chronologically when the story is the point.
4. **Outline** (`deck/outline.md`): one block per slide with the slide number, the takeaway
   headline, the single idea, the evidence or visual it shows, the speaker notes (what is said
   aloud in a speaker deck; context and caveats in a reading deck) and the source. First slide
   states the answer; middle slides build one reason each; last slide states the ask, not "Thank
   you". Slide count follows the slot and the working density: about one slide per two minutes for
   a speaker deck, as many as the argument needs for a reading deck (whose slides carry the
   evidence in full sentences instead of leaving it to the presenter).
5. **Q&A bank** and **rehearsal notes** (`deck/qa-and-rehearsal.md`): the five to ten hardest
   questions with short answers and the slide that backs each; timing per section, transitions,
   where to cut if time shrinks, and the line to say first.

**Gate.** Show the takeaway, the pyramid, the working density and the headline list (headlines
read in order should tell the whole story). The user approves, or names changes and you revise.
Record the approval, the density and any change in a Decisions line at the top of
`deck/narrative.md`.

## Phase 2: format

Decide with the user, then write the decision at the top of `deck/outline.md`.

| If the deck will be... | Build as | With |
| --- | --- | --- |
| Edited by others, presented from PowerPoint, Keynote or Google Slides, emailed or attached, or must follow a corporate template | Editable `.pptx` | `pptx` skill; `ppt-master` when installed and the user wants its layouts; the OpenAI Slides skill (`slides`, Codex catalog) in Codex |
| Presented from a browser, shared as a link or one file, motion-rich, or the user wants a distinctive visual identity | HTML deck | `frontend-slides` |
| Both an editable file and a web version | Build the `.pptx` first, then ask before converting; do not maintain two sources of truth | as above |

Then confirm the **density** that Phase 1 set from the occasion, because it changes everything
downstream:

| | Speaker deck | Reading deck |
| --- | --- | --- |
| Read by | A live audience while the presenter talks | One reader, alone, later |
| Text per slide | Headline plus at most one visual or three short bullets (about 30 words) | Headline plus full-sentence body, labelled charts, sources on the slide (about 80-120 words) |
| Where the argument lives | In the speaker notes and the presenter | On the slides themselves |
| Speaker notes | Required: what is said aloud | Optional: context and caveats |
| Slide count | About one per two minutes | As many as the argument needs |

Do not compromise with one hybrid deck; if the same material serves both, build the speaker deck
and put the reading detail in an appendix section or a separate memo (`exec-summary` or
`executive-communication` when installed).

**A density change reopens the outline gate.** The approved outline was written for the Phase 1
density: slide count, speaker notes and body copy all differ between the two columns above. If the
user picks the other density here, do not start Phase 3. Revise `deck/outline.md` (slide count,
notes, body copy) to the new density, show the takeaway and the new headline list again, and
record the new approval in the Decisions line. The build phase only ever receives an outline
approved for the density it is built to.

**If the matching skill is not installed,** keep the format the user confirmed:

- `.pptx`: fall back to `python-pptx` when Python can import it. It is the same format built
  another way, so no new decision is needed; say so in the handback.
- HTML: build a single self-contained HTML file by hand (see the `frontend-slides` bullet below).

If no route can produce the confirmed format (for example a `.pptx` with no `pptx` skill and no
importable `python-pptx`), never switch formats on your own: the user chose it for who edits and
presents the deck. Say what is missing and offer the options (the HTML deck, the user installing
`python-pptx`, or stopping at paste-ready copy), then wait for the answer. Stop after Phase 1 only
when the user chooses that or declines every alternative: give them `deck/outline.md` as
paste-ready slide copy and state that no deck file was created.

## Phase 3: build

Hand the build skill the outline file by path, plus the format, density, template or style
constraints, the output path (`deck/<slug>.pptx` or `deck/<slug>.html`) and the rule that the
outline is fixed. Do not paste a summary in place of the outline and do not let the builder
restructure it: a builder that wants to split, merge or reorder slides reports back, and you decide
with the user. Put the speaker notes from the outline into the deck's notes field (`.pptx`) or a
notes panel or `data-notes` attribute (HTML).

- `.pptx`: one title placeholder per slide, real placeholders and layouts rather than loose text
  boxes, native charts from the real data, images with alternative text, a slide number.
- HTML: `frontend-slides` runs its own style exploration; supply the audience and mood from Phase
  1 so the previews fit, and keep every slide inside one viewport.
- Charts: label axes and units, state the takeaway in the chart title, cite the source on the
  slide. Use `dataviz` when installed.

Build in a scratch pass first if the deck is long: first, middle and last slides, check them, then
the rest.

## Phase 4: QA

Run `references/deck-qa-checklist.md` against the built file. The core of it:

1. **Render** every slide to an image when the toolchain allows (the checklist gives the
   `.pptx` and HTML routes) and look at the images, not only the XML or the DOM. If rendering is
   not possible, say "not rendered" in the QA summary and run the structural checks only.
2. **Check** overflow and clipping, alignment and margins, contrast, minimum type size, one idea
   per slide, headlines that state the takeaway (read the headlines alone, in order: they must
   tell the story), speaker notes present on every slide of a speaker deck, sources on every
   figure, and consistency of fonts, colours and spacing.
3. **Fix and re-render** until the checks pass or three rounds have run; list what still fails.
4. Compare the headline list with `deck/outline.md`; any drift is a bug in the deck, not a
   reason to rewrite the outline.

## Handback

Report: the deck path and format, slide count, density, the outline, narrative and Q&A files, the
gate decisions and who made them, what was rendered and at what size versus what was not, the
checks that failed and remain, any `[needed: ...]` placeholders still open, and how to present or
edit it (open command, notes view, where the theme variables or master slides live).

## Skills and tools this leans on

- **pptx** (and **ppt-master**, or the OpenAI Slides skill in Codex) - when installed, Phase 3
  builds the editable deck with them. Otherwise use `python-pptx`; if that is unavailable too,
  ask the user before using the HTML route or stopping at paste-ready copy, as described in
  Phase 2.
- **frontend-slides** - when installed, Phase 3 builds HTML decks with it and inherits its
  viewport-fit rules. Otherwise build a single self-contained HTML file with one section per
  slide, `clamp()` type and keyboard navigation (still the confirmed HTML format). Suggesting
  the `.pptx` route instead is a format change and needs the user's say-so.
- **bluf**, **minto-pyramid**, **exec-summary**, **slide-deck**, **executive-communication** -
  when installed, use them in Phase 1 for the BLUF, the pyramid, the one-page version and the
  slide discipline. Otherwise the templates in `references/narrative-templates.md` are the whole
  method.
- **dataviz** - when installed, use it for charts in Phase 3. Otherwise label axes and units,
  start bar charts at zero, cite the source, and use at most five colours.
- **Rendering toolchain** - when `soffice` (LibreOffice) and `pdftoppm` (poppler) are on the
  path, or a browser automation tool (the Claude Code browser pane, a Playwright MCP or `npx
  playwright screenshot`) is available, render in Phase 4. Otherwise report "not rendered".
