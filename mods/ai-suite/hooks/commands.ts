// What a press asks for, as data (the pane's tree holds no `$`, so the hook runs it), and
// the confirm card: the commands that wait for a Yes, how they are remembered in the
// `pendingConfirm` state, and the words the card says. Pure; no `$` in here.
import type {
  AiSuiteAnchor,
  AiSuiteInstalledFilter,
  AiSuiteScopeFilter,
  AiSuiteView,
} from '../types'
import { settingLabel } from './presets'
import { namesLine } from './selection'
import type { PaneData } from './state'
import { filterMissing, plural, updatable } from './summary'

export type Named = { scope: string; name: string }

/** The two views that filter by tag and tick skills, which are also the ids of their pagers. */
export type TagList = 'install' | 'installed'
export type SelectList = TagList

/** What a selection bar applies to every ticked skill it names. */
export type BulkVerb = 'install' | 'update' | 'relink' | 'retire'

export type Command =
  | { kind: 'view'; view: AiSuiteView; installed?: AiSuiteInstalledFilter }
  | { kind: 'refresh' }
  | { kind: 'page'; list: string; page: number }
  | { kind: 'scope'; value: AiSuiteScopeFilter }
  | { kind: 'state'; value: AiSuiteInstalledFilter }
  | { kind: 'query'; text: string }
  | { kind: 'tag'; list: TagList; value: string }
  | { kind: 'select'; list: SelectList; id: string }
  | { kind: 'select-all'; list: SelectList; ids: string[] }
  | { kind: 'clear-selection'; list: SelectList }
  | { kind: 'bulk'; list: SelectList; verb: BulkVerb; ids: string[] }
  | { kind: 'install'; row: Named }
  | { kind: 'install-all'; scope: AiSuiteScopeFilter; query: string; tag: string }
  | { kind: 'update'; row: Named }
  | { kind: 'update-changed' }
  | { kind: 'relink'; row: Named }
  | { kind: 'retire'; row: Named }
  | { kind: 'files'; row: Named }
  | { kind: 'close-detail' }
  | { kind: 'fetch' }
  | { kind: 'pull' }
  | { kind: 'apply' }
  | { kind: 'set'; key: string; value: string }
  | { kind: 'custom'; key: string | null }
  | { kind: 'reset'; key: string }
  | { kind: 'create-config' }
  | { kind: 'preview'; name: string }
  | { kind: 'workflow-retire'; name: string }
  | { kind: 'workflow-push'; name: string }
  | { kind: 'yes' }
  | { kind: 'no' }

/** One press: the control's key, what it asks for, and whether a confirm card comes first (and, if so, where it is drawn). */
export type Act = { key: string; command: Command; confirm?: true; anchor?: AiSuiteAnchor }

/** The confirm card of a press that named no place: under the header. */
export const TOP: AiSuiteAnchor = { kind: 'top', key: 'pane' }
/** Under the skill (or workflow) card whose Box key is `key`. */
export const cardAnchor = (key: string): AiSuiteAnchor => ({ kind: 'card', key })
/** Under the button row (or control) the view named `key`. */
export const rowAnchor = (key: string): AiSuiteAnchor => ({ kind: 'row', key })
/** In the place of a list's selection bar. */
export const barAnchor = (list: SelectList): AiSuiteAnchor => ({ kind: 'bar', key: list })
export const sameAnchor = (a: AiSuiteAnchor, b: AiSuiteAnchor): boolean => a.kind === b.kind && a.key === b.key

export const idOf = (row: Named): string => `${row.scope}/${row.name}`

// ------------------------------------------------------------------- confirm

const CONFIRMABLE: readonly string[] = [
  'retire',
  'bulk',
  'pull',
  'install-all',
  'update-changed',
  'apply',
  'workflow-retire',
  'workflow-push',
  'reset',
]

/** The command a confirm card will run on Yes, as the text kept in `pendingConfirm`. */
export const encodeConfirm = (command: Command): string => JSON.stringify(command)

/** Reads a kept confirm back; null for anything that is not one of the confirmable commands. */
export function decodeConfirm(text: string): Command | null {
  try {
    const value: unknown = JSON.parse(text)
    if (typeof value !== 'object' || value === null) return null
    const kind = (value as { kind?: unknown }).kind
    return typeof kind === 'string' && CONFIRMABLE.includes(kind) ? (value as Command) : null
  } catch {
    return null
  }
}

/** The card's words: the question, the names it is about (a bulk action), one sentence of consequence, and the Yes button's label. */
export type Confirm = { question: string; names?: string; detail: string; yes: string }

const BACKUPS = '~/.agents/backups'

export function confirmOf(command: Command, data: PaneData): Confirm {
  const rows = data.snapshots.status.data ?? []
  const updates = data.snapshots.updates.data
  const backups = data.snapshots.config.data?.['paths.backups_dir'] ?? BACKUPS
  switch (command.kind) {
    case 'retire':
      return {
        question: `Retire ${idOf(command.row)}?`,
        detail: `Its files move to ${backups}; nothing is deleted.`,
        yes: 'Yes, retire',
      }
    case 'bulk':
      return {
        question: `Retire ${plural(command.ids.length, 'skill', 'skills')}?`,
        names: namesLine(command.ids),
        detail: `Their files move to ${backups}; nothing is deleted.`,
        yes: `Yes, retire ${command.ids.length}`,
      }
    case 'pull': {
      const behind = updates?.git.behind ?? 0
      return {
        question: behind > 0 ? `Pull ${plural(behind, 'commit', 'commits')} from upstream?` : 'Pull from upstream?',
        detail: 'Runs git pull --ff-only in the repo; local commits are never rewritten.',
        yes: 'Yes, pull',
      }
    }
    case 'install-all': {
      const count = filterMissing(rows, {
        installScope: command.scope,
        installQuery: command.query,
        installTag: command.tag,
      }).length
      return {
        question: `Install ${plural(count, 'missing skill', 'missing skills')}?`,
        detail: 'They are copied or linked into place; existing files are never overwritten.',
        yes: `Yes, install ${count}`,
      }
    }
    case 'update-changed': {
      const count = updatable(rows, updates).length
      return {
        question: `Update ${plural(count, 'changed skill', 'changed skills')}?`,
        detail: `Each is replaced by the repo copy; yours moves to ${backups} first.`,
        yes: `Yes, update ${count}`,
      }
    }
    case 'apply':
      return {
        question: 'Apply this configuration to the machine?',
        detail: 'Runs install.sh --headless --auto, then syncs settings into your existing files.',
        yes: 'Yes, apply',
      }
    case 'workflow-retire':
      return {
        question: `Retire workflow ${command.name}?`,
        detail: `Its folder and tool links move to ${backups}; nothing is deleted.`,
        yes: 'Yes, retire',
      }
    case 'workflow-push':
      return {
        question: `Copy workflow ${command.name} into the repo?`,
        detail: `It lands in shared/skills/${command.name}; commit it yourself afterwards.`,
        yes: 'Yes, push',
      }
    case 'reset':
      return {
        question: `Reset ${settingLabel(command.key)} to its default?`,
        detail: `Runs config reset ${command.key}; every other setting is left alone.`,
        yes: 'Yes, reset',
      }
    default:
      return { question: 'Go ahead?', detail: '', yes: 'Yes' }
  }
}
