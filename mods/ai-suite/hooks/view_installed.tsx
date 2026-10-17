// Installed: every skill on this machine as a card, narrowed by filter chips, with the repairs it offers.
import type { AiSuiteInstalledFilter, AiSuiteSkillRow } from '../types'
import { idOf } from './commands'
import { CARDS_PER_PAGE, filterInstalled, pageOf } from './summary'
import {
  PROBLEM_BADGE,
  STATE_BADGES,
  actButton,
  buttonRow,
  card,
  chips,
  column,
  entry,
  heading,
  hue,
  linesOf,
  skillCard,
  toneProps,
} from './ui'
import type { Badge, Env, Tone } from './ui'
import { empty, note, pager } from './ui_parts'

const FILTER_CHIPS: readonly { value: AiSuiteInstalledFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'modified', label: 'Modified' },
  { value: 'problems', label: 'Problems' },
  { value: 'foreign', label: 'Foreign' },
  { value: 'tool-managed', label: 'Tool-managed' },
]

const FILE_LINES = 16

function linkTone(state: string): Tone {
  if (state === 'ok') return 'success'
  return state === 'missing' ? 'dim' : 'error'
}

/** `claude ●  codex ●`: green when the link is right, red when broken, dim when not made. */
function linkDots(env: Env, row: AiSuiteSkillRow): JSX.Element | null {
  if (row.links.length === 0) return null
  const { Box, Text } = env.els
  return (
    <Box flexDirection="row" gap={2}>
      {row.links.map(link => (
        <Box flexDirection="row" gap={1}>
          <Text dimColor>{link.consumer}</Text>
          <Text {...(env.isDesktop ? { color: hue(linkTone(link.state)) } : toneProps(linkTone(link.state)))}>●</Text>
        </Box>
      ))}
    </Box>
  )
}

function filesCard(env: Env, id: string, text: string): JSX.Element {
  const { Text } = env.els
  const all = linesOf(env, text)
  const shown = all.slice(0, FILE_LINES)
  return card(
    env,
    `files-card:${id}`,
    null,
    heading(env, 'Files', id),
    entry(
      env,
      ...shown.map(each => <Text wrap="truncate">{each}</Text>),
      all.length > shown.length && <Text dimColor>{`… ${all.length - shown.length} more lines`}</Text>,
    ),
    buttonRow(env, actButton(env, { key: 'close-files', command: { kind: 'close-detail' } }, 'Close')),
  )
}

function installedCard(env: Env, row: AiSuiteSkillRow): JSX.Element {
  const id = idOf(row)
  const named = { scope: row.scope, name: row.name }
  const detail = env.data.detail
  const isFilesOpen = detail?.kind === 'files' && detail.id === id
  const stateBadge: Badge = STATE_BADGES[row.state] ?? { glyph: '·', word: row.state, tone: 'dim' }
  const summary =
    row.hasProblem && row.note !== ''
      ? { text: `! ${row.note}`, tone: 'warning' as const }
      : { text: row.description === '' ? '(no description)' : row.description, tone: 'dim' as const }
  return skillCard(env, {
    scope: row.scope,
    name: row.name,
    badges: row.hasProblem ? [stateBadge, PROBLEM_BADGE] : [stateBadge],
    summary,
    aside: row.scope === 'shared' ? linkDots(env, row) : null,
    buttons: [
      row.state === 'modified' &&
        actButton(env, { key: `update:${id}`, command: { kind: 'update', row: named } }, 'Update', { lead: true }),
      row.canRelink && actButton(env, { key: `relink:${id}`, command: { kind: 'relink', row: named } }, 'Relink'),
      row.canRetire &&
        actButton(env, { key: `retire:${id}`, command: { kind: 'retire', row: named }, confirm: true }, 'Retire…'),
      row.state !== 'ignored' &&
        actButton(env, { key: `files:${id}`, command: { kind: 'files', row: named } }, isFilesOpen ? 'Hide files' : 'Files'),
    ],
  })
}

export function installed(env: Env): JSX.Element {
  const { Box } = env.els
  const { status } = env.data.snapshots
  const { installed: filter } = env.data.filters
  const everything = filterInstalled(status.data ?? [], 'all')
  const shown = filterInstalled(status.data ?? [], filter)
  const paged = pageOf(shown, env.data.pages.installed ?? 0, CARDS_PER_PAGE)
  const detail = env.data.detail
  return (
    <Box {...column(env)}>
      {note(env, status, 'skills')}
      {status.data !== null &&
        chips(
          env,
          FILTER_CHIPS.map(chip => ({
            key: chip.value,
            label: chip.label,
            isActive: chip.value === filter,
            act: { key: `installed-filter:${chip.value}`, command: { kind: 'state', value: chip.value } },
          })),
        )}
      {status.data !== null && everything.length === 0 &&
        empty(env, 'Nothing is installed yet.', actButton(env, { key: 'installed-open-install', command: { kind: 'view', view: 'install' } }, 'Open Install'))}
      {everything.length > 0 && shown.length === 0 &&
        empty(env, 'No skill matches this filter.', actButton(env, { key: 'installed-show-all', command: { kind: 'state', value: 'all' } }, 'Show all'))}
      {paged.items.flatMap(row => [
        installedCard(env, row),
        detail?.kind === 'files' && detail.id === idOf(row) ? filesCard(env, detail.id, detail.text) : null,
      ])}
      {pager(env, 'installed', paged, shown.length, CARDS_PER_PAGE)}
      <Box>{actButton(env, { key: 'refresh', command: { kind: 'refresh' } }, 'Refresh')}</Box>
    </Box>
  )
}
