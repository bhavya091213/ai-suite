// The rest of the shared pieces: empty states and notes, the error callout, the pager, the confirm
// card, the progress bar with its numbers, list rows and the two-column settings rows. Like ui.tsx
// they branch on the surface themselves (`env.isDesktop`) so that no view has to.
import type { BoxProps, SelectProps } from 'claude-code'
import type { AiSuiteAnchor, AiSuiteSnapshot } from '../types'
import { truncate } from './cli'
import { confirmOf, decodeConfirm, sameAnchor } from './commands'
import type { Act, TagList } from './commands'
import { ALL_TAGS, tagOptions } from './presets'
import type { TagCount } from './presets'
import type { Page } from './summary'
import { barSegments, scopeParts } from './summary'
import type { BarSegments, CountPart, ScopeCount } from './summary'
import { above, actButton, buttonRow, below, card, fit, hue, toneProps, wrapText } from './ui'
import type { Aside, Child, Env, Tone } from './ui'

// -------------------------------------------------------------- empties, notes

/** One dim sentence and, if given, the one button that answers it (`answerWidth` cells are kept for the button). */
export function empty(env: Env, text: string, answer?: JSX.Element, answerWidth = 16): JSX.Element {
  const { Box, Text } = env.els
  return (
    <Box key="empty" flexDirection="row" gap={env.isDesktop ? 2 : 1} alignItems="center" {...below(env)}>
      <Text dimColor wrap="truncate">{fit(env, text, answer === undefined ? 0 : answerWidth)}</Text>
      {answer}
    </Box>
  )
}

// ------------------------------------------------------------------ tags

const TAG_LABEL = 'Tag'
/** Cells a Select draws around its label and value: the space after the label and the ends of the picker (a little more on the desktop's native picker). */
const selectTrim = (env: Env): number => (env.isDesktop ? 9 : 7)

/** What the tag Select of a list needs: the tags (with counts) the list holds and the one picked. */
export type TagPick = { list: TagList; present: readonly TagCount[]; current: string }

/**
 * The `Tag` Select that goes with a view's filter chips (`All tags`, then the ones the rows
 * carry, in canonical order, each with its count). A pick filters the list and sends its pager
 * back to page 1 (`tag` in actions.ts). Nothing is drawn while the rows carry no tag.
 */
export function tagAside(env: Env, pick: TagPick): Aside | undefined {
  if (pick.present.length === 0 && pick.current === ALL_TAGS) return undefined
  const { Select } = env.els
  const options = tagOptions(pick.present, pick.current)
  const widest = Math.max(...options.map(option => (option.label ?? option.value).length))
  const key = `tag:${pick.list}`
  const onSelect = (value: string): Promise<void> =>
    value === pick.current
      ? Promise.resolve()
      : env.dispatch({ key, command: { kind: 'tag', list: pick.list, value } })
  return {
    key: `filters:${pick.list}`,
    element: <Select key={key} label={TAG_LABEL} options={options} value={pick.current} onSelect={onSelect} />,
    width: TAG_LABEL.length + widest + selectTrim(env),
  }
}

/** `No skill tagged design matches.` and the button that lifts the tag filter. */
export function tagEmpty(env: Env, list: TagList, tag: string): JSX.Element {
  const answer = actButton(
    env,
    { key: `${list}-show-all-tags`, command: { kind: 'tag', list, value: ALL_TAGS } },
    'Show all tags',
  )
  return empty(env, `No skill tagged ${tag} matches.`, answer, 20)
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
  const { Box, Text } = env.els
  return card(
    env,
    `callout:${title}`,
    'error',
    <Box flexDirection="column">
      <Text bold color="error">{title}</Text>
      {wrapText(text, env.inner, 4).map(each => <Text>{each}</Text>)}
    </Box>,
    ...extra,
  )
}

// --------------------------------------------------------------------- pager

export const showing = (paged: Page<unknown>, total: number, size: number): string =>
  `Showing ${paged.page * size + 1}-${Math.min(total, paged.page * size + paged.items.length)} of ${total}`

const PAGER_SIDE = 14

/**
 * `‹ Prev`, `Showing 1-5 of 26`, `Next ›`; nothing while everything fits one page. A view's pager
 * sits a blank row below the list on the desktop; one inside a card passes `{}` for `margin`.
 */
export function pager(
  env: Env,
  list: string,
  paged: Page<unknown>,
  total: number,
  size: number,
  margin: Pick<BoxProps, 'marginTop'> = above(env),
): JSX.Element | null {
  if (paged.pages <= 1) return null
  const { Box, Text } = env.els
  const prev = paged.page > 0 &&
    actButton(env, { key: `prev:${list}`, command: { kind: 'page', list, page: paged.page - 1 } }, env.isDesktop ? '‹ Previous' : '‹ Prev', env.isDesktop ? { plain: true } : {})
  const next = paged.page < paged.pages - 1 &&
    actButton(env, { key: `next:${list}`, command: { kind: 'page', list, page: paged.page + 1 } }, 'Next ›', env.isDesktop ? { plain: true } : {})
  if (!env.isDesktop) {
    return (
      <Box key={`pager:${list}`} flexDirection="row" gap={1} marginBottom={1}>
        {prev}
        <Text dimColor>{showing(paged, total, size)}</Text>
        {next}
      </Box>
    )
  }
  return (
    <Box key={`pager:${list}`} flexDirection="row" justifyContent="space-between" alignItems="center" width="100%" {...margin}>
      <Box width={PAGER_SIDE} justifyContent="flex-start">{prev}</Box>
      <Text dimColor>{showing(paged, total, size)}</Text>
      <Box width={PAGER_SIDE} justifyContent="flex-end">{next}</Box>
    </Box>
  )
}

// ------------------------------------------------------------ confirm card

/**
 * The highlighted card that replaces a two-press confirm: question, consequence and the two
 * answers. The terminal answers with `[y]` and `[n]`; the desktop with a primary and a plain button.
 */
export function confirmCard(env: Env): JSX.Element | null {
  const pending = env.data.pending
  if (pending === null) return null
  const { Box, Text } = env.els
  const command = decodeConfirm(pending.command)
  const keys = env.isDesktop ? {} : { plain: true as const }
  const cancel = actButton(env, { key: 'confirm-no', command: { kind: 'no' } }, 'Cancel', {
    ...keys,
    hotkey: 'n',
    isLive: true,
  })
  const row = (...buttons: JSX.Element[]): JSX.Element =>
    env.isDesktop ? (
      <Box flexDirection="row" gap={1} justifyContent="flex-start">{buttons}</Box>
    ) : (
      buttonRow(env, ...buttons) ?? <Text> </Text>
    )
  if (command === null) {
    return card(env, 'confirm', 'warning', <Text bold>This confirmation is no longer valid.</Text>, row(cancel))
  }
  const words = confirmOf(command, env.data)
  const yes = actButton(env, { key: 'confirm-yes', command: { kind: 'yes' } }, words.yes, {
    ...keys,
    hotkey: 'y',
    primary: true,
    isLive: true,
  })
  return card(
    env,
    'confirm',
    'warning',
    <Box flexDirection="column">
      <Text bold wrap="truncate">{fit(env, words.question)}</Text>
      {words.names !== undefined && wrapText(words.names, env.inner, 3).map(each => <Text>{each}</Text>)}
      {wrapText(words.detail, env.inner, 2).map(each => <Text dimColor>{each}</Text>)}
    </Box>,
    row(yes, cancel),
  )
}

/**
 * The confirm card, but only where it belongs: a view puts this right after the card, button row
 * or bar a press named (`anchor`) and it draws nothing unless that press is the pending one.
 */
export function confirmAfter(env: Env, anchor: AiSuiteAnchor): JSX.Element | null {
  const pending = env.data.pending
  return pending !== null && sameAnchor(pending.anchor, anchor) ? confirmCard(env) : null
}

// -------------------------------------------------------- progress and numbers

/** Units across the desktop bar's viewBox; the Svg stretches to the card. */
const BAR_UNITS = 1000
const BAR_HEIGHT = 8
const TRACK = '#808080'
const INSTALLED = '#3fa65b'
const MODIFIED = '#e0a526'

/** The desktop bar: a track, the installed and modified share over it (modified after, so it ends the filled part). */
export function barSource(segments: BarSegments): string {
  const filled = segments.ok + segments.mod
  const rect = (fill: string, x: number, width: number, opacity = ''): string =>
    `<rect${x > 0 ? ` x="${x}"` : ''} width="${width}" height="${BAR_HEIGHT}" rx="4" fill="${fill}"${opacity}/>`
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${BAR_UNITS} ${BAR_HEIGHT}" width="100%" preserveAspectRatio="none">` +
    rect(TRACK, 0, BAR_UNITS, ' fill-opacity="0.25"') +
    (filled > 0 ? rect(INSTALLED, 0, filled) : '') +
    (segments.mod > 0 ? rect(MODIFIED, segments.ok, segments.mod) : '') +
    '</svg>'
  )
}

/** A scope's bar: an 8 px Svg on the desktop, a line of `━` (installed, modified) and `─` (missing) in the terminal. */
export function progress(env: Env, count: ScopeCount): JSX.Element {
  const { Box, Text } = env.els
  const offered = count.installed + count.modified + count.missing
  const present = count.installed + count.modified
  if (env.isDesktop && env.Svg !== null) {
    const { Svg } = env
    const segments = barSegments(count.installed, count.modified, offered, BAR_UNITS)
    return <Svg source={barSource(segments)} alt={`${present} of ${offered} installed`} height={BAR_HEIGHT} />
  }
  const cells = barSegments(count.installed, count.modified, offered, env.inner)
  return (
    <Box flexDirection="row">
      {cells.ok > 0 && <Text color="success">{'━'.repeat(cells.ok)}</Text>}
      {cells.mod > 0 && <Text color="warning">{'━'.repeat(cells.mod)}</Text>}
      {cells.rest > 0 && <Text dimColor>{'─'.repeat(cells.rest)}</Text>}
    </Box>
  )
}

/** The numbers under a bar: one dim line in the terminal; coloured numbers and dim words, two apart, on the desktop. */
export function counts(env: Env, count: ScopeCount): JSX.Element {
  const { Box, Text } = env.els
  const parts = scopeParts(count)
  if (!env.isDesktop) {
    const text = parts.map(part => `${part.value} ${part.word}`).join(' · ')
    return <Text dimColor wrap="truncate">{fit(env, text)}</Text>
  }
  const tone = (part: CountPart): Tone => (part.value === 0 ? 'dim' : part.tone)
  return (
    <Box flexDirection="row" flexWrap="wrap" gap={2}>
      {parts.map(part => (
        <Box flexDirection="row" gap={1}>
          <Text color={hue(tone(part))}>{String(part.value)}</Text>
          <Text dimColor>{part.word}</Text>
        </Box>
      ))}
    </Box>
  )
}

/** One item with the button that answers it: `• text` in the terminal, a coloured `●` and the text on the desktop. */
export function listRow(env: Env, tone: Tone, text: string, act: Act, label: string): JSX.Element {
  const { Box, Text } = env.els
  const room = fit(env, text, label.length + 6)
  const button = actButton(env, act, label)
  if (!env.isDesktop) {
    return (
      <Box flexDirection="row" justifyContent="space-between" gap={1}>
        <Text {...toneProps(tone)} wrap="truncate">{`• ${room}`}</Text>
        {button}
      </Box>
    )
  }
  return (
    <Box flexDirection="row" justifyContent="space-between" alignItems="center" gap={2}>
      <Box flexDirection="row" gap={1}>
        <Text color={hue(tone === 'plain' ? 'dim' : tone)}>●</Text>
        <Text wrap="truncate">{room}</Text>
      </Box>
      {button}
    </Box>
  )
}

// ---------------------------------------------------------------- settings rows

export const LABEL_WIDTH = 26

/** A setting's name in its fixed-width column (dim on the desktop). */
export function labelCell(env: Env, text: string): JSX.Element {
  const { Box, Text } = env.els
  return (
    <Box width={LABEL_WIDTH}>
      <Text {...(env.isDesktop ? { dimColor: true as const } : {})} wrap="truncate">{truncate(text, LABEL_WIDTH - 1)}</Text>
    </Box>
  )
}

/** Where a row that belongs to a setting (its `Custom…` field) starts: under the control, past the label column. */
export const indent = (env: Env): { marginLeft?: number } => (env.isDesktop ? { marginLeft: LABEL_WIDTH + 2 } : {})

type Pick3 = Pick<SelectProps, 'options' | 'value' | 'onSelect'>

/** A setting that is a pick from a list: the Select carrying its label in the terminal, label and Select in two columns on the desktop. */
export function pickRow(env: Env, key: string, text: string, pick: Pick3): JSX.Element {
  const { Box, Select } = env.els
  if (!env.isDesktop) return <Select key={key} label={text.padEnd(LABEL_WIDTH)} {...pick} />
  return (
    <Box flexDirection="row" gap={2} alignItems="center">
      {labelCell(env, text)}
      <Box flexGrow={1}>
        <Select key={key} {...pick} />
      </Box>
    </Box>
  )
}
