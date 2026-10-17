// The skill card and its badges: name, scope, tags and state badges on a title row (with a tick
// box at its start where skills can be selected), one description line and one button line. The
// same pieces as ui.tsx's: a pure function of PaneData, branching on the surface here so no view has to.
import { truncate } from './cli'
import type { Act } from './commands'
import { actButton, buttonRow, card, entry, fit, hue, titleRow, toneProps } from './ui'
import type { Child, Env, Tone } from './ui'

// -------------------------------------------------------------------- badges

/** The terminal draws `glyph word` in the tone; the desktop draws `● word` in the matching theme colour. */
export type Badge = { glyph: string; word: string; tone: Tone }

export const STATE_BADGES: Record<string, Badge> = {
  installed: { glyph: '✓', word: 'installed', tone: 'success' },
  modified: { glyph: '≠', word: 'modified', tone: 'warning' },
  'not-installed': { glyph: '·', word: 'missing', tone: 'dim' },
  foreign: { glyph: '?', word: 'foreign', tone: 'magenta' },
  ignored: { glyph: '⚙', word: 'tool-managed', tone: 'dim' },
}
export const PROBLEM_BADGE: Badge = { glyph: '!', word: 'problem', tone: 'error' }

export const badgeWidth = (env: Env, item: Badge): number => item.word.length + (env.isDesktop ? 2 : item.glyph.length + 1)

export function badge(env: Env, item: Badge): JSX.Element {
  const { Text } = env.els
  return env.isDesktop ? (
    <Text color={hue(item.tone)} wrap="truncate">{`● ${item.word}`}</Text>
  ) : (
    <Text {...toneProps(item.tone)} wrap="truncate">{`${item.glyph} ${item.word}`}</Text>
  )
}

// ---------------------------------------------------------------- tick boxes

export const TICKED = '☑'
export const UNTICKED = '☐'

/** The tick box: a plain button of one square glyph, the only one that reads as a checkbox on every surface. */
export type Tick = { act: Act; isOn: boolean }

/** Cells the tick box takes on the title row, with the gap after it. */
const TICK_CELLS = 3

export type SkillCard = {
  scope: string
  name: string
  /** Drawn dim after the scope (`shared · design · frontend`, the first three); left off when there are none or the card is too narrow for them. */
  tags?: readonly string[]
  badges: readonly Badge[]
  /** The second line: the description, or what is wrong. */
  summary: { text: string; tone: Tone }
  /** Something drawn at the left of the button line (the link dots). */
  aside?: JSX.Element | null
  /** The tick box at the start of the title row; a ticked card has Claude's colour for its border. */
  tick?: Tick
  buttons: readonly Child[]
}

/** Room the name keeps on the title line before the tags give way. */
const NAME_ROOM = 12
/** Tags a card shows; the rest are one pick away in the Select. */
const CARD_TAGS = 3

/** `· design · frontend`, dim, cut to the room the line has beside the scope, the badges and a short name; null when there is none. */
function tagLine(env: Env, spec: SkillCard, taken: number): string | null {
  const shown = (spec.tags ?? []).slice(0, CARD_TAGS)
  if (shown.length === 0) return null
  const room = env.inner - taken - Math.min(spec.name.length, NAME_ROOM) - 1
  return room < 8 ? null : truncate(`· ${shown.join(' · ')}`, room)
}

/** The skill card of the spec: name, scope, tags and state badges; one description line; one button line. */
export function skillCard(env: Env, spec: SkillCard): JSX.Element {
  const { Box, Text } = env.els
  const scope = env.isDesktop ? spec.scope : `[${spec.scope}]`
  const taken =
    scope.length +
    spec.badges.reduce((sum, item) => sum + badgeWidth(env, item) + 1, 0) +
    (env.isDesktop ? 4 : 1) +
    (spec.tick === undefined ? 0 : TICK_CELLS)
  const tagText = tagLine(env, spec, taken)
  const used = taken + (tagText === null ? 0 : tagText.length + 1)
  const buttons = buttonRow(env, ...spec.buttons)
  return card(
    env,
    `card:${spec.scope}/${spec.name}`,
    spec.tick?.isOn === true ? 'magenta' : null,
    entry(
      env,
      titleRow(
        env,
        [
          spec.tick !== undefined && actButton(env, spec.tick.act, spec.tick.isOn ? TICKED : UNTICKED, { plain: true }),
          <Text bold wrap="truncate">{fit(env, spec.name, used)}</Text>,
          <Text dimColor>{scope}</Text>,
          tagText !== null && <Text dimColor wrap="truncate">{tagText}</Text>,
        ],
        spec.badges.map(item => badge(env, item)),
      ),
      <Text {...toneProps(spec.summary.tone)} wrap="truncate">{fit(env, spec.summary.text)}</Text>,
    ),
    spec.aside ? (
      <Box flexDirection="row" justifyContent="space-between">
        {spec.aside}
        {buttons}
      </Box>
    ) : (
      buttons
    ),
  )
}
