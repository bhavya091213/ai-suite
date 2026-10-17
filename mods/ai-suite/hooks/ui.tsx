// The pieces every view is built from: the header, cards, badges, buttons, the confirm card, the
// error callout, the pager, empty states and width-aware truncation. All of it is drawing: a
// pure function of PaneData, with a button's press handed to `dispatch` (the hook binds its `$`).
import type { Elements } from 'claude-code'
import type { AiSuiteSnapshot } from '../types'
import { truncate } from './cli'
import { confirmOf, decodeConfirm } from './commands'
import type { Act } from './commands'
import { VIEWS } from './state'
import type { PaneData } from './state'
import { plural, skillCounts } from './summary'
import type { Page } from './summary'

/** The three elements every surface has: all the band draws with. */
export type Els = Pick<Elements['terminal'], 'Box' | 'Text' | 'Button'>
/** What the pane draws with: the terminal, desktop and editor tables hold all five. */
export type PaneEls = Els & Pick<Elements['terminal'], 'Input' | 'Select'>
export type Dispatch = (act: Act) => Promise<void>

export type Env = {
  els: PaneEls
  data: PaneData
  /** Cells across the pane's body. */
  columns: number
  /** Cells of text inside a card (its border and padding taken out). */
  inner: number
  dispatch: Dispatch
  /** True while a command runs or a confirm card is up: card buttons draw dim. */
  isLocked: boolean
}

export function makeEnv(els: PaneEls, data: PaneData, bodyColumns: number, dispatch: Dispatch): Env {
  const columns = bodyColumns > 0 ? bodyColumns : 60
  return {
    els,
    data,
    columns,
    inner: Math.max(16, columns - 4),
    dispatch,
    isLocked: data.busy !== null || data.pending !== null,
  }
}

// --------------------------------------------------------------------- text

export type Tone = 'plain' | 'dim' | 'success' | 'warning' | 'error' | 'magenta'

export const toneProps = (tone: Tone): { dimColor?: true; color?: string } =>
  tone === 'plain' ? {} : tone === 'dim' ? { dimColor: true } : { color: tone }

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
  hotkey?: string
  /** Drawn without brackets (a tab, a chip, a confirm answer). */
  plain?: true
  /** Draws the active tab or chip: bold and underlined. */
  isActive?: boolean
  /** Draw at full strength even while the pane is locked (the confirm card's own answers). */
  isLive?: true
}

export function actButton(env: Env, act: Act, label: string, options: ButtonOptions = {}): JSX.Element {
  const { Button, Text } = env.els
  const extra = {
    ...(options.hotkey === undefined ? {} : { hotkey: options.hotkey }),
    ...(options.primary === true ? { variant: 'primary' as const } : {}),
    ...(options.plain === true ? { plain: true as const } : {}),
    ...(env.isLocked && options.isLive !== true ? { dimColor: true } : {}),
  }
  const press = () => env.dispatch(act)
  if (options.isActive === true) {
    return (
      <Button key={act.key} label={label} {...extra} onPress={press}>
        <Text bold underline>{label}</Text>
      </Button>
    )
  }
  return <Button key={act.key} label={label} {...extra} onPress={press} />
}

/** A row of plain filter chips; the chosen one is bold and underlined. */
export function chips(
  env: Env,
  items: readonly { key: string; label: string; isActive: boolean; act: Act }[],
): JSX.Element {
  const { Box } = env.els
  return (
    <Box flexDirection="row" flexWrap="wrap" gap={2} marginBottom={1}>
      {items.map(item => actButton(env, item.act, item.label, { plain: true, isActive: item.isActive }))}
    </Box>
  )
}

// --------------------------------------------------------------------- cards

export type Child = JSX.Element | false | null | undefined

export function card(env: Env, key: string, accent: Tone | null, ...children: Child[]): JSX.Element {
  const { Box } = env.els
  const border = accent === null ? {} : { borderColor: accent }
  return (
    <Box key={key} borderStyle="round" paddingX={1} paddingY={0} flexDirection="column" marginBottom={1} {...border}>
      {children}
    </Box>
  )
}

/** A card's heading: the title in bold and, dim after it, a count or a hint. */
export function heading(env: Env, title: string, hint = ''): JSX.Element {
  const { Box, Text } = env.els
  return (
    <Box flexDirection="row" gap={1}>
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

/** A card's row of buttons, pushed to the right. */
export function buttonRow(env: Env, ...buttons: Child[]): JSX.Element | null {
  const shown = buttons.filter(button => button !== false && button !== null && button !== undefined)
  if (shown.length === 0) return null
  const { Box } = env.els
  return (
    <Box flexDirection="row" gap={1} justifyContent="flex-end">
      {shown}
    </Box>
  )
}

// -------------------------------------------------------------------- badges

export type Badge = { text: string; tone: Tone }

export const STATE_BADGES: Record<string, Badge> = {
  installed: { text: '✓ installed', tone: 'success' },
  modified: { text: '≠ modified', tone: 'warning' },
  'not-installed': { text: '· missing', tone: 'dim' },
  foreign: { text: '? foreign', tone: 'magenta' },
  ignored: { text: '⚙ tool-managed', tone: 'dim' },
}
export const PROBLEM_BADGE: Badge = { text: '! problem', tone: 'error' }

export function badge(env: Env, item: Badge): JSX.Element {
  const { Text } = env.els
  return <Text {...toneProps(item.tone)} wrap="truncate">{item.text}</Text>
}

export type SkillCard = {
  scope: string
  name: string
  badges: readonly Badge[]
  /** The second line: the description, or what is wrong. */
  summary: { text: string; tone: Tone }
  /** Something drawn at the left of the button line (the link dots). */
  aside?: JSX.Element | null
  buttons: readonly Child[]
}

/** The skill card of the spec: name, scope badge and state badges; one description line; one button line. */
export function skillCard(env: Env, spec: SkillCard): JSX.Element {
  const { Box, Text } = env.els
  const scope = `[${spec.scope}]`
  const used = scope.length + spec.badges.reduce((sum, item) => sum + item.text.length + 1, 0) + 1
  const buttons = buttonRow(env, ...spec.buttons)
  return card(
    env,
    `card:${spec.scope}/${spec.name}`,
    null,
    <Box flexDirection="row" gap={1}>
      <Text bold wrap="truncate">{fit(env, spec.name, used)}</Text>
      <Text dimColor>{scope}</Text>
      {spec.badges.map(item => badge(env, item))}
    </Box>,
    <Text {...toneProps(spec.summary.tone)} wrap="truncate">{fit(env, spec.summary.text)}</Text>,
    (spec.aside || buttons) && (
      <Box flexDirection="row" justifyContent="space-between" marginTop={0}>
        {spec.aside ?? <Text> </Text>}
        {buttons}
      </Box>
    ),
  )
}

// ----------------------------------------------------------- notes and empties

/** One dim sentence and, if given, the one button that answers it. */
export function empty(env: Env, text: string, answer?: JSX.Element): JSX.Element {
  const { Box, Text } = env.els
  return (
    <Box key="empty" flexDirection="row" gap={1} marginBottom={1}>
      <Text dimColor wrap="truncate">{fit(env, text, answer === undefined ? 0 : 16)}</Text>
      {answer}
    </Box>
  )
}

/** What a snapshot says before its data can be drawn: not loaded, failed, or older than the last refresh. */
export function note(env: Env, snap: AiSuiteSnapshot<unknown>, what: string): JSX.Element | null {
  const { Text } = env.els
  if (snap.data === null && snap.error === null) return <Text dimColor>{`Loading ${what}…`}</Text>
  if (snap.data === null) {
    return card(env, `load-error:${what}`, 'error', <Text color="error" wrap="truncate">{fit(env, `${what}: ${snap.error ?? ''}`)}</Text>)
  }
  if (snap.error === null) return null
  return <Text color="warning" wrap="truncate">{truncate(`Showing older ${what}; the last refresh failed: ${snap.error}`, env.columns)}</Text>
}

/** The red-bordered callout: a title and the message, wrapped to the card (never inside one line). */
export function callout(env: Env, title: string, text: string, ...extra: Child[]): JSX.Element {
  const { Text } = env.els
  return card(
    env,
    `callout:${title}`,
    'error',
    <Text bold color="error">{title}</Text>,
    ...wrapText(text, env.inner, 4).map(each => <Text>{each}</Text>),
    ...extra,
  )
}

// --------------------------------------------------------------------- pager

export const showing = (paged: Page<unknown>, total: number, size: number): string =>
  `Showing ${paged.page * size + 1}-${Math.min(total, paged.page * size + paged.items.length)} of ${total}`

/** `‹ Prev`, `Showing 1-5 of 26`, `Next ›`; nothing while everything fits one page. */
export function pager(env: Env, list: string, paged: Page<unknown>, total: number, size: number): JSX.Element | null {
  if (paged.pages <= 1) return null
  const { Box, Text } = env.els
  return (
    <Box key={`pager:${list}`} flexDirection="row" gap={1} marginBottom={1}>
      {paged.page > 0 && actButton(env, { key: `prev:${list}`, command: { kind: 'page', list, page: paged.page - 1 } }, '‹ Prev')}
      <Text dimColor>{showing(paged, total, size)}</Text>
      {paged.page < paged.pages - 1 &&
        actButton(env, { key: `next:${list}`, command: { kind: 'page', list, page: paged.page + 1 } }, 'Next ›')}
    </Box>
  )
}

// ------------------------------------------------------------ confirm card

/** The highlighted card that replaces a two-press confirm: question, consequence, `[y]` and `[n]`. */
export function confirmCard(env: Env): JSX.Element | null {
  const pending = env.data.pending
  if (pending === null) return null
  const { Text } = env.els
  const command = decodeConfirm(pending)
  const cancel = actButton(env, { key: 'confirm-no', command: { kind: 'no' } }, 'Cancel', {
    plain: true,
    hotkey: 'n',
    isLive: true,
  })
  if (command === null) {
    return card(env, 'confirm', 'warning', <Text bold>This confirmation is no longer valid.</Text>, buttonRow(env, cancel))
  }
  const words = confirmOf(command, env.data)
  const yes = actButton(env, { key: 'confirm-yes', command: { kind: 'yes' } }, words.yes, {
    plain: true,
    hotkey: 'y',
    primary: true,
    isLive: true,
  })
  return card(
    env,
    'confirm',
    'warning',
    <Text bold wrap="truncate">{fit(env, words.question)}</Text>,
    ...wrapText(words.detail, env.inner, 2).map(each => <Text dimColor>{each}</Text>),
    buttonRow(env, yes, cancel),
  )
}

// -------------------------------------------------------------------- header

type Segment = { text: string; tone: Tone }

function strip(data: PaneData): Segment[] {
  const { status, updates } = data.snapshots
  const out: Segment[] = []
  if (status.data !== null) {
    const counts = skillCounts(status.data, updates)
    out.push({ text: `${counts.present}/${counts.offered} installed`, tone: counts.present === counts.offered ? 'success' : 'plain' })
    if (counts.changed > 0) out.push({ text: plural(counts.changed, 'update', 'updates'), tone: 'warning' })
    if (counts.problems > 0) out.push({ text: plural(counts.problems, 'issue', 'issues'), tone: 'error' })
  } else {
    out.push({ text: status.error === null ? 'Loading…' : 'status unavailable', tone: status.error === null ? 'dim' : 'error' })
  }
  if (data.busy !== null) out.push({ text: `Working… ${data.busy.label}`, tone: 'warning' })
  return out
}

function repoLine(data: PaneData): Segment {
  const { repo } = data
  if (repo !== null && repo.error !== '') return { text: 'repo not found', tone: 'error' }
  const git = data.snapshots.updates.data?.git
  const parts = [
    repo?.shown ?? '',
    git?.branch ?? '',
    git === undefined ? '' : git.behind > 0 ? `${git.behind} behind` : '',
  ].filter(part => part !== '')
  return { text: parts.join(' · '), tone: 'dim' }
}

/** Title and repo line, the tab row (hotkeys `o i s u t w d`) and the status strip. */
export function header(env: Env): JSX.Element {
  const { Box, Text } = env.els
  const title = 'AI Suite · Skills'
  const right = repoLine(env.data)
  const segments = strip(env.data)
  return (
    <Box key="header" flexDirection="column" marginBottom={1}>
      <Box flexDirection="row" justifyContent="space-between">
        <Text bold>{title}</Text>
        <Text {...toneProps(right.tone)} wrap="truncate">{truncate(right.text, Math.max(8, env.columns - title.length - 2))}</Text>
      </Box>
      <Box flexDirection="row" flexWrap="wrap" gap={1}>
        {VIEWS.map(entry =>
          actButton(env, { key: `view-${entry.id}`, command: { kind: 'view', view: entry.id } }, entry.label, {
            plain: true,
            hotkey: entry.hotkey,
            isActive: entry.id === env.data.view,
          }),
        )}
      </Box>
      <Box flexDirection="row" gap={1}>
        {segments.flatMap((segment, at) => [
          at > 0 ? <Text key={`dot-${at}`} dimColor>·</Text> : null,
          <Text key={`segment-${at}`} {...toneProps(segment.tone)} wrap="truncate">{segment.text}</Text>,
        ])}
      </Box>
    </Box>
  )
}
