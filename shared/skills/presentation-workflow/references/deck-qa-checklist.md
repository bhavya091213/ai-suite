# Deck QA checklist

Phase 4 reference. Work top to bottom on the built file. Record each check as pass, fail
(with the slide numbers) or not run (with the reason) in a short QA summary; never write "all
checks passed" for checks that were not run.

## Contents

1. Render the slides
2. Structure and story
3. Layout
4. Type and contrast
5. Visuals and data
6. Notes
7. Consistency
8. Accessibility
9. File hygiene
10. QA summary format

---

## 1. Render the slides

Look at images of the slides, not only at the file's XML or DOM. Put renders in
`deck/_render/` and leave them there (retire with `mv`, never `rm`).

**Editable `.pptx`** (needs LibreOffice `soffice` and poppler `pdftoppm` on the path):

```bash
soffice --headless --convert-to pdf --outdir deck/_render deck/<slug>.pptx
pdftoppm -r 80 -png deck/_render/<slug>.pdf deck/_render/slide
```

Then open the PNGs (`slide-01.png`, ...) with the host's image reader. A contact sheet of six to
twelve slides per image is enough for the first pass; zoom on any slide that looks wrong.
Fonts that are missing on the rendering machine change line breaks; note the substitution.

**HTML deck**: take screenshots with browser automation (the Claude Code browser pane, a Playwright
MCP, or `npx playwright screenshot`) at 1920x1080 and 1280x720, plus 768x1024 and 375x667 when the
deck is meant to work on small screens. Step through every slide with the keyboard (arrow keys
or space) and capture each one; check that the controller reaches the last slide.

**No toolchain**: say "not rendered". For `.pptx`, still run the structural checks with
`python-pptx`: every shape's `left + width` and `top + height` stay inside the slide, every
slide has a title placeholder with text, no text frame holds more words than the density allows.

## 2. Structure and story

- [ ] Slide count and the headline list match `deck/outline.md`; no slide added, merged or
      reordered without a recorded decision.
- [ ] Reading the headlines alone, in order, tells the whole story.
- [ ] Every headline states a takeaway (a sentence with a verb), not a topic.
- [ ] One idea per slide; a slide that argues two things is split.
- [ ] Slide 1 states the answer; the last slide states the ask, not "Thank you" or "Questions?".
- [ ] Sections build one reason at a time, strongest first unless the outline says otherwise.
- [ ] Appendix slides are marked as such and are not part of the timed run.

## 3. Layout

- [ ] No text overflows its box, is clipped by the slide edge or collides with another element
      (look at the render; line breaks differ from the editor's).
- [ ] Margins are equal on all four sides (at least 5% of the slide width) and nothing sits in
      the footer or slide-number zone.
- [ ] Elements that should align do: left edges of titles and bodies share one line, columns
      share baselines, gaps between repeated items are equal.
- [ ] Text is not placed on busy image regions; a scrim or a clear zone is used.
- [ ] HTML decks: every slide fits one viewport with no internal scrolling at each tested size.
- [ ] Content density matches the chosen type. Speaker deck: at most one visual or three short
      bullets and about 30 words. Reading deck: about 80-120 words with sources on the slide.

## 4. Type and contrast

- [ ] Minimum sizes at 16:9 (1920x1080 reference): headline 36pt or larger, body 24pt or larger
      in a speaker deck, 16pt or larger in a reading deck, footnotes and sources 12pt or larger.
      Never solve overflow by shrinking below these; split the slide.
- [ ] No more than two type families; hierarchy comes from size and weight.
- [ ] Contrast meets WCAG AA: 4.5:1 for body text, 3:1 for text at 24pt or larger and for chart
      lines and control outlines. Check text over images and over coloured fills.
- [ ] Light text on a projector: avoid pale grey on white and thin weights below 24pt.
- [ ] Colour is not the only carrier of meaning (charts also use labels, patterns or direct
      annotation).

## 5. Visuals and data

- [ ] Every figure on a slide traces to a source named on the slide or in the notes; no
      `[needed: ...]` marker remains unless it is listed as open in the handback.
- [ ] Charts: titled with the takeaway, axes and units labelled, bar charts start at zero, legend
      only when direct labels are impossible, no more than five series colours, no 3D effects.
- [ ] Numbers on the slide match the source file and each other (totals add up; percentages and
      absolute values agree between slides).
- [ ] Images are sharp at the projected size, licensed or owned, and cropped on purpose.
- [ ] Diagrams read left-to-right or top-to-bottom, with no crossing lines that can be avoided.
- [ ] Animations and transitions, if any, serve the story (reveal a step, show a change); remove
      the rest. HTML decks honour `prefers-reduced-motion`.

## 6. Notes

- [ ] Speaker deck: every slide has speaker notes that say what is spoken, including the
      transition to the next slide.
- [ ] Reading deck: notes, where present, hold context and caveats rather than the argument.
- [ ] Notes are in the deck's notes field or panel, not on the slide face.
- [ ] Notes contain nothing the audience must not see if the file is shared (internal remarks,
      names of people who are not in the room).

## 7. Consistency

- [ ] Fonts, sizes, colours and spacing come from the master or the theme variables, not from
      per-slide overrides.
- [ ] Titles sit in the same position on every content slide; repeated layouts look identical.
- [ ] Slide numbers, dates and footers are present or absent consistently.
- [ ] Capitalisation, number formats, date formats and units are consistent.
- [ ] Terminology matches the outline and the pyramid (one name per concept).

## 8. Accessibility

- [ ] Every non-decorative image and chart has alternative text; decorative ones are marked.
- [ ] Reading order follows the visual order (title first); `.pptx` titles are real title
      placeholders so outline view and screen readers work.
- [ ] Links have descriptive text, not a bare "click here".
- [ ] HTML decks: semantic structure, keyboard-only navigation works, visible focus, readable
      zoomed to 200%.

## 9. File hygiene

- [ ] No leftover placeholder text, empty placeholders, "Lorem ipsum", draft watermarks or
      hidden slides (unless listed as intended).
- [ ] No tracked changes, comments or review marks in a file that will be sent out.
- [ ] Document properties (author, title, company) are correct and carry no personal or
      machine-specific paths.
- [ ] File name is descriptive, lower-case with hyphens; the path in the handback is relative
      to the repo or project root.
- [ ] A PDF export exists when the plan calls for one (backup for the room, sharing); it was
      produced from the final file.
- [ ] Fonts are available on the presenting machine or embedded; a fallback is noted if not.

## 10. QA summary format

```markdown
## QA summary - <deck file>
- Rendered: yes (soffice + pdftoppm, 80 dpi, 14 slides) | HTML at 1920x1080, 1280x720 | no (reason)
- Passed: <sections or check names>
- Fixed: <slide numbers - what was wrong - what changed>
- Still failing: <slide numbers - what - why not fixed>
- Not run: <checks and reasons>
- Open placeholders: <list of [needed: ...] items>
```
