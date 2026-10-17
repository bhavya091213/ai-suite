// The pieces every view is built from: the surface-aware environment, text and buttons, cards,
// badges and the skill card. All of it is drawing: a pure function of PaneData, with a button's
// press handed to `dispatch` (the hook binds its `$`). The surface branch lives here and in
// ui_parts.tsx / pane.tsx, so the views stay surface-agnostic: the terminal is a character grid
// (bordered cards, hotkeys, `━` bars), the desktop app and the editor are not (padded cards, a
// blank row between things, an Svg bar, tabs without key caps).
import type { BoxProps, Elements } from 'claude-code'
import { truncate } from './cli'
import type { Act } from './commands'
import type { PaneData } from './state'

/** The three elements every surface has: all the band draws with. */
export type Els = Pick<Elements['terminal'], 'Box' | 'Text' | 'Button'>
/** What the pane draws with: the terminal, desktop and editor tables hold all five. */
export type PaneEls = Els & Pick<Elements['terminal'], 'Input' | 'Select'>
/** The vector leaf the desktop and the editor have and the terminal lacks. */
export type SvgEl = Elements['desktop']['Svg']
export type Surface = 'terminal' | 'desktop' | 'vscode'
export type Look = { surface: Surface; Svg: SvgEl | null }
export const TERMINAL_LOOK: Look = { surface: 'terminal', Svg: null }
export type Dispatch = (act: Act) => Promise<void>

export type Env = {
  els: PaneEls
  data: PaneData
  /** Cells across the pane's body. */
  columns: number
  /** Cells of text inside a card (the pane's padding, the card's border and padding taken out). */
  inner: number
  dispatch: Dispatch
  /** True while a command runs or a confirm card is up: card buttons draw dim. */
  isLocked: boolean
  /** True on the desktop app and the editor: spacing instead of margins, no hotkeys, an Svg bar. */
  isDesktop: boolean
  Svg: SvgEl | null
}

// Root padding 2+2, card border 1+1, card padding 2+2 on the desktop; border 1+1 and padding 1+1 in the terminal.
const DESKTOP_CHROME = 10
const TERMINAL_CHROME = 4

export function makeEnv(
  els: PaneEls,
  data: PaneData,
  bodyColumns: number,
  dispatch: Dispatch,
  look: Look = TERMINAL_LOOK,
): Env {
  const columns = bodyColumns > 0 ? bodyColumns : 60
  const isDesktop = look.surface !== 'terminal'
  return {
    els,
    data,
    columns,
    inner: Math.max(16, columns - (isDesktop ? DESKTOP_CHROME : TERMINAL_CHROME)),
    dispatch,
    isLocked: data.busy !== null || data.pending !== null,
    isDesktop,
    Svg: look.Svg,
  }
}

// ------------------------------------------------------------------- spacing

/** A view's column: on the desktop one blank row between its children, in the terminal none (cards bring a margin). */
export const column = (env: Env): Pick<BoxProps, 'flexDirection' | 'gap'> =>
  env.isDesktop ? { flexDirection: 'column', gap: 1 } : { flexDirection: 'column' }

/** The blank row under a terminal block; the desktop spaces with `gap` instead. */
export const below = (env: Env): Pick<BoxProps, 'marginBottom'> => (env.isDesktop ? {} : { marginBottom: 1 })

// --------------------------------------------------------------------- text

export type Tone = 'plain' | 'dim' | 'success' | 'warning' | 'error' | 'magenta'

export const toneProps = (tone: Tone): { dimColor?: true; color?: string } =>
  tone === 'plain' ? {} : tone === 'dim' ? { dimColor: true } : { color: tone }

/** The theme key a tone is drawn in on the desktop (dim is `subtle`, magenta is Claude's accent). */
const HUES: Record<Tone, string> = {
  plain: 'text',
  dim: 'subtle',
  success: 'success',
  warning: 'warning',
  error: 'error',
  magenta: 'claude',
}
export const hue = (tone: Tone): string => HUES[tone]

/** Cuts `text` to the card's inner width less `used` cells already taken on the line. */
export const fit = (env: Env, text: string, used = 0): string => truncate(text, Math.max(8, env.inner - used))

/** Breaks `text` at spaces into at most `maxLines` lines of `width` cells; the last one ends in `…` if cut. */
export function wrapText(text: string, width: number, maxLines: number): string[] {
  const out: string[] = []
  let line = ''
  for (const word of text.replace(/\s+/g, ' ').trim().split(' ')) {
    const next = line === '' ? word : `${line} ${word}`
    if (next.length <= width || line === '') {
      line = next
    } else {
      out.push(line)
      line = word
    }
  }
  if (line !== '') out.push(line)
  const kept = out.slice(0, maxLines).map(each => truncate(each, width))
  const last = kept.length - 1
  return out.length > maxLines && last >= 0 ? [...kept.slice(0, last), truncate(`${out[last] ?? ''} …`, width)] : kept
}

/** The lines of a block of text, each cut to the card (a file tree, a preview, command output). */
export const linesOf = (env: Env, text: string): string[] =>
  text.split('\n').map(line => (line.length > env.inner ? `${line.slice(0, env.inner - 1)}…` : line))

// ------------------------------------------------------------------- buttons

export type ButtonOptions = {
  primary?: true
  /** A card's main action: primary on the desktop, an ordinary button in the terminal. */
  lead?: true
  /** Shown in the terminal only: the desktop draws a hotkey as a key cap, so it is left off there. */
  hotkey?: string
  /** Drawn without brackets (a tab, a chip, a confirm answer). */
  plain?: true
  /** Draws a tab or chip: the chosen one bold and underlined (in Claude's colour on the desktop), the rest dim there. */
  isActive?: boolean
  /** Draw at full strength even while the pane is locked (the confirm card's own answers). */
  isLive?: true
}

export function actButton(env: Env, act: Act, label: string, options: ButtonOptions = {}): JSX.Element {
  const { Button, Text } = env.els
  const isIdle = env.isDesktop && options.isActive === false
  const isPrimary = options.primary === true || (options.lead === true && env.isDesktop)
  const extra = {
    ...(options.hotkey === undefined || env.isDesktop ? {} : { hotkey: options.hotkey }),
    ...(isPrimary ? { variant: 'primary' as const } : {}),
    ...(options.plain === true ? { plain: true as const } : {}),
    ...((env.isLocked && options.isLive !== true) || isIdle ? { dimColor: true } : {}),
  }
  const press = () => env.dispatch(act)
  if (options.isActive === true) {
    const accent = env.isDesktop ? { color: 'claude' as const } : {}
    return (
      <Button key={act.key} label={label} {...extra} onPress={press}>
        <Text bold underline {...accent}>{label}</Text>
      </Button>
    )
  }
  return <Button key={act.key} label={label} {...extra} onPress={press} />
}

export type ChipItem = { key: string; label: string; isActive: boolean; act: Act }

/** A control that goes with the chips: at their right edge when the row has room for it, under them when not. */
export type Aside = { key: string; element: JSX.Element; width: number }

/** Cells the pane's own padding takes from a desktop row (two on each side). */
const DESKTOP_GUTTER = 4

/** A row of plain filter chips; the chosen one is bold and underlined. */
export function chips(env: Env, items: readonly ChipItem[], aside?: Aside): JSX.Element {
  const { Box } = env.els
  const row = (look: BoxProps): JSX.Element => (
    <Box flexDirection="row" flexWrap="wrap" gap={2} {...look}>
      {items.map(item => actButton(env, item.act, item.label, { plain: true, isActive: item.isActive }))}
    </Box>
  )
  if (aside === undefined) return row(below(env))
  // the labels, two cells after each (between them, and before the aside)
  const used = items.reduce((sum, item) => sum + item.label.length + 2, 0) + aside.width
  const isBeside = used <= env.columns - (env.isDesktop ? DESKTOP_GUTTER : 0)
  return isBeside ? (
    <Box key={aside.key} flexDirection="row" justifyContent="space-between" alignItems="center" gap={2} {...below(env)}>
      {row({})}
      {aside.element}
    </Box>
  ) : (
    <Box key={aside.key} flexDirection="column" {...below(env)}>
      {row({})}
      {aside.element}
    </Box>
  )
}

export type Child = JSX.Element | false | null | undefined

const present = (items: readonly Child[]): JSX.Element[] =>
  items.filter((item): item is JSX.Element => item !== false && item !== null && item !== undefined)

/** A card's row of buttons, pushed to the right. */
export function buttonRow(env: Env, ...buttons: Child[]): JSX.Element | null {
  const shown = present(buttons)
  if (shown.length === 0) return null
  const { Box } = env.els
  return (
    <Box flexDirection="row" gap={1} justifyContent="flex-end">
      {shown}
    </Box>
  )
}

/** A view's row of actions, from the left, wrapping when the pane is narrow. */
export function actionRow(env: Env, ...buttons: Child[]): JSX.Element | null {
  const shown = present(buttons)
  if (shown.length === 0) return null
  const { Box } = env.els
  return (
    <Box flexDirection="row" flexWrap="wrap" gap={1} justifyContent="flex-start">
      {shown}
    </Box>
  )
}

// --------------------------------------------------------------------- cards

const BORDERS: Record<Tone, string> = { ...HUES, plain: 'inactive', dim: 'inactive' }

export function card(env: Env, key: string, accent: Tone | null, ...children: Child[]): JSX.Element {
  const { Box } = env.els
  const look: BoxProps = env.isDesktop
    ? { paddingX: 2, paddingY: 1, gap: 1, width: '100%', borderColor: BORDERS[accent ?? 'plain'] }
    : { paddingX: 1, paddingY: 0, marginBottom: 1, ...(accent === null ? {} : { borderColor: accent }) }
  return (
    <Box key={key} borderStyle="round" flexDirection="column" {...look}>
      {children}
    </Box>
  )
}

/** A card's heading: the title in bold and, dim after it (at the far edge on the desktop), a count or a hint. */
export function heading(env: Env, title: string, hint = ''): JSX.Element {
  const { Box, Text } = env.els
  const look: BoxProps = env.isDesktop ? { justifyContent: 'space-between', gap: 2 } : { gap: 1 }
  return (
    <Box flexDirection="row" {...look}>
      <Text bold wrap="truncate">{fit(env, title, hint.length + 1)}</Text>
      {hint !== '' && <Text dimColor wrap="truncate">{hint}</Text>}
    </Box>
  )
}

/** A line of body text in a card, cut to its width. */
export function line(env: Env, text: string, tone: Tone = 'plain'): JSX.Element {
  const { Text } = env.els
  return <Text {...toneProps(tone)} wrap="truncate">{fit(env, text)}</Text>
}

/** A card row's title line: what it is called on the left, its badges or meta on the right (the desktop pushes them apart). */
export function titleRow(env: Env, left: readonly Child[], right: readonly JSX.Element[]): JSX.Element {
  const { Box } = env.els
  if (!env.isDesktop) {
    return (
      <Box flexDirection="row" gap={1}>
        {left}
        {right}
      </Box>
    )
  }
  return (
    <Box flexDirection="row" justifyContent="space-between" gap={2}>
      <Box flexDirection="row" gap={1}>{left}</Box>
      <Box flexDirection="row" gap={2}>{right}</Box>
    </Box>
  )
}

/** A title line and the line under it, kept together even where the card spaces its children apart. */
export function entry(env: Env, ...lines: Child[]): JSX.Element {
  const { Box } = env.els
  return <Box flexDirection="column">{lines}</Box>
}

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
  const taken = scope.length + spec.badges.reduce((sum, item) => sum + badgeWidth(env, item) + 1, 0) + (env.isDesktop ? 4 : 1)
  const tagText = tagLine(env, spec, taken)
  const used = taken + (tagText === null ? 0 : tagText.length + 1)
  const buttons = buttonRow(env, ...spec.buttons)
  return card(
    env,
    `card:${spec.scope}/${spec.name}`,
    null,
    entry(
      env,
      titleRow(
        env,
        [
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
