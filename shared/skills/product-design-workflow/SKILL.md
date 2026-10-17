---
name: product-design-workflow
description: Five-phase, gated product design and UX workflow that takes a product or feature from a written brief through a sitemap and user-flow diagrams, two or three distinct visual directions, a prototype and a build verified in the browser, writing docs/product-brief.md, docs/sitemap.md, docs/user-flows.md and a screen inventory on the way. Use when the user says "design the UX", "sitemap", "user flows", "visual direction", "prototype", "design this app/feature/screen", or wants screens planned and approved before anything is built.
origin: local
---

# Product design workflow

Design a product in five phases: understand it, plan the UX, establish a visual direction,
prototype, then build and verify. Each phase ends with files the user can read, and two of them
end with a gate: the structure (sitemap and flows) is approved before any pixel is chosen, and
the direction is picked by the user before anything is prototyped. The user owns the decisions
about what the product is and how it should feel; you own the craft in between. The workflow
reads the same in Claude Code and Codex; where a host tool matters, both are named.

Four rules that never bend:

1. **A sitemap is not a user-flow diagram - produce both.** The sitemap says what exists and
   where it lives; a flow says what a person does, in what order, and what happens when it goes
   wrong. Neither can be derived from the other, and a project with only one is half designed.
2. **Honesty about artefacts.** Never claim a Figma file, FigJam board, prototype, screenshot or
   visual test exists unless this session created or ran it. When a tool was unavailable, write
   "not created" or "not run", never "verified".
3. **Nothing generic, nothing arbitrary.** Every visual choice serves the product, its audience
   or its content; apply `references/anti-generic-checklist.md` before a direction is shown.
   Novelty for its own sake fails the same test as a template.
4. **Never delete.** Never run `rm` / `rm -rf`, directly or via a subagent. Relocate with `mv`
   instead. If something must be retired, `mv` it into a backup location (e.g.
   `~/.agents/backups/retired-<what>/`) and say so in the report.

Helpers beside this file: `references/deliverable-templates.md` (skeletons for the brief, the
sitemap, the flows document and the screen inventory table) and
`references/anti-generic-checklist.md` (the test every direction and screen must pass).

## Phases

| Phase | Output | Gate |
| --- | --- | --- |
| 1 Understand the product | `docs/product-brief.md` | none; open questions listed |
| 2 Plan the UX | `docs/sitemap.md`, `docs/user-flows.md`, screen inventory | User approves sitemap and flows |
| 3 Establish visual direction | 2-3 direction boards, direction brief | User picks a direction |
| 4 Prototype | Figma/FigJam frames, or `prototype/` HTML | none |
| 5 Build and verify | Screens in the project stack, verification report | none |

Record every gate decision in the Decisions section of `docs/product-brief.md`. After a context
compaction, re-read the three docs instead of re-deriving them.

## Phase 1: understand the product

Read before asking: the README, existing routes or screens, brand assets, a design system if
there is one, analytics or support tickets the user points at, competitor links. Do not ask for
anything that can be read. Then ask, in one or two rounds (bounded choices through the host's
question tool, `AskUserQuestion` in Claude Code; plain questions otherwise):

- **Product**: what it is in one sentence, and the job it must do first.
- **Audience**: who, on what device, how often, with what expertise; the one person to design for.
- **Goal and metric**: the business outcome and the number that shows it happened.
- **Constraints**: platforms, stack, brand rules, accessibility target (WCAG level), timeline,
  existing design system or none.
- **Non-goals**: what is explicitly out of scope for this round.

Write `docs/product-brief.md` from the template, summarise it in five lines, and list the open
questions. Proceed only when none of them would change the sitemap; an unknown audience or
platform stops here.

## Phase 2: plan the UX

Produce two documents and one table, and keep them distinct.

**Sitemap** (`docs/sitemap.md`): a hierarchical page tree as a nested list no deeper than three
levels (deeper means a new section), every page with its route pattern and parameters, the
navigation model (primary, secondary, utility, contextual; what is reachable from where), and the
access requirement per page (public, signed-in, role, plan). Use `information-architecture` when
installed for labelling, URL structure and taxonomy.

**User flows** (`docs/user-flows.md`): one Mermaid `flowchart` per primary journey (three to six
of them), each covering the alternate paths (skip, back, branch), the errors (validation,
network, permission denied, expired session), the empty states (nothing yet, no results, still
loading) and the recovery from each error and empty state back onto the happy path. A flow with
only a happy path is a draft, not a deliverable. Use the `userflow` dispatcher when installed to
pull in the relevant `flow-*` patterns.

**Screen inventory** (a table in `docs/user-flows.md` or its own `docs/screens.md`): screen,
route, purpose, primary action, states (empty, loading, error, success), responsive behaviour
(what changes at desktop, tablet and mobile) and the flow that owns it. Every screen in a flow
appears here; every screen here appears in the sitemap.

**Gate.** Present the three together with the open questions resolved. The user approves them,
or asks for changes and you revise. Nothing in Phase 3 starts before that approval, and a change
to the sitemap or a flow later goes back through this gate.

## Phase 3: establish visual direction

Mine the brief, not a template: the subject's industry, materials and vernacular, the audience's
context, and the content that will actually be on screen are where distinctive choices come
from. Load `frontend-design` when installed for the aesthetic reasoning.

Produce two or three **distinct** directions, not shades of one. Each has a name, a paragraph
tying it to the brief, typography (one or two families, with a scale), a palette with roles and
contrast ratios, layout and density, a motion stance, an imagery and iconography stance, and one
built reference screen: the key screen from the inventory as a single HTML file in
`design/directions/<name>.html` with real copy, or a Figma frame when the MCP is connected.
Directions are shown, never described in the abstract.

Run `references/anti-generic-checklist.md` on each direction before showing it; fix or drop the
ones that fail. Then **gate**: the user picks one direction or names what to combine. Write the
chosen direction into the Visual direction section of `docs/product-brief.md` with the tokens
(colour, type, spacing, radius, motion) that Phases 4 and 5 will use.

## Phase 4: prototype

- **Figma MCP connected**: create a page and frames for the screens in the inventory in the file
  the user names, apply the chosen direction's tokens, and link frames along the primary flows
  where the tool allows. If the user wants the flows on a board, build them in FigJam. Report
  exactly the file, page and frame names the tool returned.
- **Otherwise**: build a clickable HTML prototype in `prototype/` (one `index.html` with hash
  routes, or one file per screen), using the direction's tokens as CSS custom properties, real
  copy from the brief and no backend. Every state in the inventory is reachable from a control
  in the prototype, including empty and error states.

Walk each primary flow in the prototype and tick it in `docs/user-flows.md`; mark the ones not
walked. Summarise what exists, where, and what was not built.

## Phase 5: build and verify

Build the screens in the project's stack from the inventory and the direction tokens, one flow
at a time, primary flow first. Apply the Impeccable refinement commands when installed, and the
anti-generic checklist in any case, before calling a screen done.

Verify in a browser at desktop (1440x900) and mobile (390x844) sizes, plus tablet (768x1024)
when it is in scope: every screen in the inventory renders, every primary flow completes end to
end, empty and error states appear when provoked, keyboard focus order follows reading order,
text meets the brief's contrast target, nothing scrolls horizontally. Use the browser automation
the host offers (the Claude Code browser pane, a Playwright MCP, or `npx playwright screenshot`);
when none is available, say which checks were not run.

## Skills and tools this leans on

- **frontend-design** - when installed, load it in Phase 3 for grounding directions in the
  subject matter and the typography and layout reasoning. Otherwise use the direction recipe
  above and the anti-generic checklist as the whole brief.
- **ux-flow-skills family** (`userflow` dispatcher and the `flow-*` skills: auth, onboarding,
  forms, checkout, search, settings, errors, empty states and the rest) - when installed, run
  `userflow` with the product scope in Phase 2; it loads the matching `flow-*` skills and can
  emit a `flow-report.html`. Otherwise write the flows from the template and check each against
  the edge-case list in it (errors, empty, recovery) by hand.
- **information-architecture** - when installed, use it in Phase 2 for the page tree, labelling,
  URL structure and taxonomy. Otherwise follow the sitemap template and its three-level rule.
- **Impeccable** - when installed, run `/impeccable init` (Claude Code) or `$impeccable` (Codex)
  once in the project after the direction is chosen so its design vocabulary matches, then use
  its refinement commands (`/critique`, `/polish`, `/typeset`, `/colorize` and the others the
  installed command list shows) in Phase 5. Otherwise the anti-generic checklist is the critique
  pass and you do it yourself.
- **Figma MCP** - when connected, Phase 3 reference screens and the Phase 4 prototype live in
  Figma or FigJam and you report what the tool created. Otherwise build HTML and say plainly
  that no Figma artefact exists.

## Handback

List the files written (brief, sitemap, flows, inventory, directions, prototype, built screens),
the two gate decisions and who made them, the flows walked and verified with the sizes checked,
the checks and artefacts that were not run or not created, and the open questions.
