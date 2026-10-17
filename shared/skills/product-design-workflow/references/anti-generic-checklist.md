# Anti-generic checklist

Run this on every visual direction before it is shown to the user (Phase 3), and again on every
built screen before it is called done (Phase 5). A direction or screen that fails an item is
fixed or dropped, not shown with an apology.

The single test behind every item: **can you say what this choice does for the product, the
audience or the content?** If the answer is "it looks modern", "it is the default" or "it was
in the template", the choice fails. The test cuts the other way too: novelty for its own sake
(an unusual layout, a quirky typeface, a motion flourish with no job) fails exactly as a template
does. Distinctive means grounded in the subject, not different for the sake of it.

## 1. Look for these defaults, and replace each one deliberately

| Smell | Why it fails | What to do instead |
| --- | --- | --- |
| Gradient backgrounds, gradient text or gradient buttons with no meaning | Reads as a template; the gradient carries no information | Flat colour from the palette; use a gradient only when it encodes something real (a scale, a heat range, a time of day) |
| A repetitive grid of identical cards (icon, heading, two lines, link) | Flattens the hierarchy: every item looks equally important when none is | Vary scale and weight by importance; use a list, table or editorial layout when items are comparable; keep a card only when the item is a self-contained, actionable object |
| Rounded containers around everything | A box around content that needs no grouping adds noise and shrinks the usable width | Group with spacing, alignment and a rule; contain only what needs a boundary (inputs, menus, dialogs, interactive objects) |
| Icons used as decoration (an icon above every heading, icons that repeat the label next to them) | Adds weight without meaning and slows scanning | Icon only where it replaces words for a known action, aids recognition in a dense list, or carries state; otherwise remove it |
| Default or system fonts, or a safe pairing chosen because everyone uses it | The product has no voice; screenshots are interchangeable with a thousand others | Pick one or two families for reasons you can state (tone, legibility at the sizes used, character set, licence); set an explicit scale; use weight and size before adding a second family |
| A stock hero (large headline, subhead, two buttons, abstract blob or device mockup) | Says nothing about this product | Lead with the real thing: the product's actual output, data, a task in progress or the content the audience came for |
| Drop shadows on every surface | Elevation stops signalling anything | Reserve elevation for things that float above the page (menus, dialogs, drag state) |
| Emoji or illustration used as filler in empty or marketing spaces | Tone drifts from the product | Use an empty state that says what is missing and offers the next action, in the product's voice |
| Placeholder copy (Lorem ipsum, "Feature one", "Your text here") | Hides layout problems that real copy would expose | Use real or realistic copy from the brief and the content model |
| Motion on everything | Competes with the task and hurts people who are motion-sensitive | Animate only to show cause and effect, orient after a change, or confirm an action; honour `prefers-reduced-motion` |

## 2. Positive tests (each must be answerable)

- **Subject**: name two things in the direction taken from the brief's industry, materials,
  audience context or content (a vocabulary, a physical object, a data shape, a place). If none
  can be named, the direction is a template.
- **Hierarchy**: squint at the key screen. The primary action and the most important content
  are identifiable in two seconds without reading.
- **Type**: the scale has a stated ratio or a short list of sizes; body text is 16px or larger on
  mobile; line length is 45-80 characters for reading text; weights are used for hierarchy, not
  decoration.
- **Colour**: every colour has a role (surface, text, accent, positive, caution, negative).
  Text and interactive controls meet the brief's contrast target (WCAG AA unless the brief says
  otherwise: 4.5:1 for body text, 3:1 for large text and control boundaries). Colour is never the
  only carrier of meaning.
- **Space**: spacing comes from one scale (for example 4, 8, 12, 16, 24, 32, 48, 64), applied
  consistently; density matches the audience (a dense tool for daily experts, an airy page for
  first-time visitors).
- **Components**: each component earns its place from the inventory; no component exists only to
  fill the layout.
- **Copy**: labels name what happens (Save draft, not Submit); headings state what the section
  is for; error text says what went wrong and how to recover.
- **Imagery**: real photography, product screenshots or purposeful diagrams; no stock
  filler; every image has alternative text or is marked decorative.
- **Consistency**: the same job looks the same everywhere (one primary-button style, one way to
  show an error, one empty-state pattern).

## 3. Distinct directions

When showing two or three directions, check they differ on at least three of: typeface family,
colour temperature and contrast, layout density, geometry (sharp, soft, mixed), motion stance and
imagery stance. Directions that differ only in hue are one direction.

## 4. Record the outcome

For each direction write one line per failed item and what was changed. When the checklist
changed the result, say so in the Visual direction section of `docs/product-brief.md`; when a
rule was broken on purpose, record the product reason next to it.
