// Installed: every skill on this machine as a card, narrowed by filter chips, with the repairs it
// offers, a tick box on every card and, once some are ticked, a bar to repair or retire them together.
import type { AiSuiteInstalledFilter, AiSuiteSkillRow } from '../types'
import { cardAnchor, idOf } from './commands'
import { ALL_TAGS } from './presets'
import { chosenRows, installedPlan } from './selection'
import { CARDS_PER_PAGE, filterInstalled, pageOf, tagCounts } from './summary'
import {
  above,
  actButton,
  buttonRow,
  card,
  chips,
  column,
  entry,
  filterArea,
  heading,
  hue,
  linesOf,
  toneProps,
} from './ui'
import type { Env, Tone } from './ui'
import { confirmAfter, empty, note, pager, tagAside, tagEmpty } from './ui_parts'
import { selectionBar } from './ui_select'
import type { BarVerb } from './ui_select'
import { PROBLEM_BADGE, STATE_BADGES, skillCard } from './ui_skill'
import type { Badge } from './ui_skill'

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
    tags: row.tags,
    badges: row.hasProblem ? [stateBadge, PROBLEM_BADGE] : [stateBadge],
    summary,
    aside: row.scope === 'shared' ? linkDots(env, row) : null,
    tick: {
      isOn: env.data.installedSelection.includes(id),
      act: { key: `select:${id}`, command: { kind: 'select', list: 'installed', id } },
    },
    buttons: [
      row.state === 'modified' &&
        actButton(env, { key: `update:${id}`, command: { kind: 'update', row: named } }, 'Update', { lead: true }),
      row.canRelink && actButton(env, { key: `relink:${id}`, command: { kind: 'relink', row: named } }, 'Relink'),
      row.canRetire &&
        actButton(
          env,
          { key: `retire:${id}`, command: { kind: 'retire', row: named }, confirm: true, anchor: cardAnchor(`card:${id}`) },
          'Retire…',
        ),
      row.state !== 'ignored' &&
        actButton(env, { key: `files:${id}`, command: { kind: 'files', row: named } }, isFilesOpen ? 'Hide files' : 'Files'),
    ],
  })
}

/** The bar's buttons: what each can do to the ticked skills, counting only the ones it applies to. */
function barVerbs(chosen: readonly AiSuiteSkillRow[]): BarVerb[] {
  const plan = installedPlan(chosen)
  const verbs: BarVerb[] = []
  if (plan.update.length > 0) {
    verbs.push({ verb: 'update', ids: plan.update.map(idOf), label: `Update ${plan.update.length}`, isPrimary: true })
  }
  if (plan.relink.length > 0) {
    verbs.push({ verb: 'relink', ids: plan.relink.map(idOf), label: `Relink ${plan.relink.length}` })
  }
  if (plan.retire.length > 0) {
    verbs.push({ verb: 'retire', ids: plan.retire.map(idOf), label: `Retire ${plan.retire.length}…`, isConfirmed: true })
  }
  return verbs
}

export function installed(env: Env): JSX.Element {
  const { Box } = env.els
  const { status } = env.data.snapshots
  const { installed: filter, installedTag: tag } = env.data.filters
  const everything = filterInstalled(status.data ?? [], 'all')
  const shown = filterInstalled(status.data ?? [], filter, tag)
  const chosen = chosenRows(everything, env.data.installedSelection)
  // the tag is what hides everything when lifting it would show something
  const isTagEmpty = tag !== ALL_TAGS && filterInstalled(status.data ?? [], filter).length > 0
  const paged = pageOf(shown, env.data.pages.installed ?? 0, CARDS_PER_PAGE)
  const detail = env.data.detail
  return (
    <Box {...column(env)}>
      {note(env, status, 'skills')}
      {status.data !== null &&
        filterArea(
          env,
          chips(
            env,
            FILTER_CHIPS.map(chip => ({
              key: chip.value,
              label: chip.label,
              isActive: chip.value === filter,
              act: { key: `installed-filter:${chip.value}`, command: { kind: 'state', value: chip.value } },
            })),
            tagAside(env, { list: 'installed', present: tagCounts(everything), current: tag }),
          ),
        )}
      {status.data !== null && chosen.length > 0 &&
        selectionBar(env, {
          list: 'installed',
          count: chosen.length,
          shownIds: shown.map(idOf),
          verbs: barVerbs(chosen),
        })}
      {status.data !== null && everything.length === 0 &&
        empty(env, 'Nothing is installed yet.', actButton(env, { key: 'installed-open-install', command: { kind: 'view', view: 'install' } }, 'Open Install'))}
      {everything.length > 0 && shown.length === 0 && isTagEmpty && tagEmpty(env, 'installed', tag)}
      {everything.length > 0 && shown.length === 0 && !isTagEmpty &&
        empty(env, 'No skill matches this filter.', actButton(env, { key: 'installed-show-all', command: { kind: 'state', value: 'all' } }, 'Show all'))}
      {paged.items.flatMap(row => [
        installedCard(env, row),
        confirmAfter(env, cardAnchor(`card:${idOf(row)}`)),
        detail?.kind === 'files' && detail.id === idOf(row) ? filesCard(env, detail.id, detail.text) : null,
      ])}
      {pager(env, 'installed', paged, shown.length, CARDS_PER_PAGE)}
      <Box {...above(env)}>{actButton(env, { key: 'refresh', command: { kind: 'refresh' } }, 'Refresh')}</Box>
    </Box>
  )
}
