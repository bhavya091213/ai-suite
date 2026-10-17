// Every $.state value the mod keeps, and the only place that touches them. The
// scan behind `claude plugin validate` follows an atom only inside the module
// that declares it, so each atom has its accessors right here and the rest of
// the mod calls those. Reads made while a ui.render hook draws subscribe the
// drawing, so a write redraws the pane by itself.
import { atom, read, update } from 'claude-code'
import type { EngineInterface } from 'claude-code'
import type {
  AiSuiteBusy,
  AiSuiteConfirm,
  AiSuiteDetail,
  AiSuiteFilters,
  AiSuiteMessage,
  AiSuiteRepo,
  AiSuiteSkillRow,
  AiSuiteSnapshot,
  AiSuiteSnapshots,
  AiSuiteUpdates,
  AiSuiteView,
} from '../types'
import type { SelectList } from './commands'
import { keepKnown, merged, toggled, without } from './selection'

export const PANE_ID = 'ai-suite'

export const VIEWS: readonly { id: AiSuiteView; label: string; hotkey: string }[] = [
  { id: 'overview', label: 'Overview', hotkey: 'o' },
  { id: 'install', label: 'Install', hotkey: 'i' },
  { id: 'installed', label: 'Installed', hotkey: 's' },
  { id: 'updates', label: 'Updates', hotkey: 'u' },
  { id: 'settings', label: 'Settings', hotkey: 't' },
  { id: 'workflows', label: 'Workflows', hotkey: 'w' },
  { id: 'doctor', label: 'Doctor', hotkey: 'd' },
]

export const DEFAULT_FILTERS: AiSuiteFilters = {
  installScope: 'all',
  installQuery: '',
  installTag: 'all',
  installed: 'all',
  installedTag: 'all',
}

export type SnapshotName = keyof AiSuiteSnapshots

export function emptySnapshot<T>(): AiSuiteSnapshot<T> {
  return { data: null, fetchedAt: null, error: null }
}

function emptySnapshots(): AiSuiteSnapshots {
  return {
    status: emptySnapshot(),
    updates: emptySnapshot(),
    workflows: emptySnapshot(),
    doctor: emptySnapshot(),
    caps: emptySnapshot(),
    configFile: emptySnapshot(),
    config: emptySnapshot(),
  }
}

const viewAtom = atom({ plugin: 'ai-suite', key: 'view' } as const, 'overview')
const pagesAtom = atom({ plugin: 'ai-suite', key: 'pages' } as const, {})
const filtersAtom = atom({ plugin: 'ai-suite', key: 'filters' } as const, DEFAULT_FILTERS)
const repoAtom = atom({ plugin: 'ai-suite', key: 'repo' } as const, null)
const snapshotsAtom = atom({ plugin: 'ai-suite', key: 'snapshots' } as const, emptySnapshots())
const busyAtom = atom({ plugin: 'ai-suite', key: 'busy' } as const, null)
const pendingAtom = atom({ plugin: 'ai-suite', key: 'pendingConfirm' } as const, null)
const messageAtom = atom({ plugin: 'ai-suite', key: 'message' } as const, null)
const customKeyAtom = atom({ plugin: 'ai-suite', key: 'customKey' } as const, null)
const detailAtom = atom({ plugin: 'ai-suite', key: 'detail' } as const, null)
const installSelectionAtom = atom({ plugin: 'ai-suite', key: 'installSelection' } as const, [])
const installedSelectionAtom = atom({ plugin: 'ai-suite', key: 'installedSelection' } as const, [])
const bandHiddenAtom = atom({ plugin: 'ai-suite', key: 'bandHidden' } as const, false)
const paneWaitingAtom = atom({ plugin: 'ai-suite', key: 'paneWaiting' } as const, false)

// ---------------------------------------------------------------- accessors

export function getView($: EngineInterface): Promise<AiSuiteView> {
  return read($, viewAtom)
}
export async function setView($: EngineInterface, view: AiSuiteView): Promise<void> {
  await update($, viewAtom, () => view)
}

/** Moves one list (by its id) to a page; the other lists keep theirs. */
export async function setPage($: EngineInterface, list: string, page: number): Promise<void> {
  await update($, pagesAtom, all => ({ ...all, [list]: Math.max(0, page) }))
}

export async function resetPages($: EngineInterface): Promise<void> {
  await update($, pagesAtom, () => ({}))
}

export function getFilters($: EngineInterface): Promise<AiSuiteFilters> {
  return read($, filtersAtom)
}
export async function patchFilters($: EngineInterface, change: Partial<AiSuiteFilters>): Promise<void> {
  await update($, filtersAtom, previous => ({ ...previous, ...change }))
}

export function getRepo($: EngineInterface): Promise<AiSuiteRepo | null> {
  return read($, repoAtom)
}
export async function setRepo($: EngineInterface, repo: AiSuiteRepo): Promise<void> {
  await update($, repoAtom, () => repo)
}

export function getSnapshots($: EngineInterface): Promise<AiSuiteSnapshots> {
  return read($, snapshotsAtom)
}

/** Changes one command's snapshot; concurrent writers to other snapshots are not lost. */
export async function patchSnapshot(
  $: EngineInterface,
  name: SnapshotName,
  change: (previous: AiSuiteSnapshot<unknown>) => AiSuiteSnapshot<unknown>,
): Promise<void> {
  await update($, snapshotsAtom, all => ({ ...all, [name]: change(all[name]) }) as AiSuiteSnapshots)
}

export async function resetSnapshots($: EngineInterface): Promise<void> {
  await update($, snapshotsAtom, () => emptySnapshots())
}

export function getBusy($: EngineInterface): Promise<AiSuiteBusy | null> {
  return read($, busyAtom)
}
export async function setBusy($: EngineInterface, busy: AiSuiteBusy | null): Promise<void> {
  await update($, busyAtom, () => busy)
}

export function getPending($: EngineInterface): Promise<AiSuiteConfirm | null> {
  return read($, pendingAtom)
}
export async function setPending($: EngineInterface, confirm: AiSuiteConfirm | null): Promise<void> {
  await update($, pendingAtom, () => confirm)
}

/** Takes the confirm that is up down and returns what it held, in a single read-and-write. */
export async function takePending($: EngineInterface): Promise<AiSuiteConfirm | null> {
  let taken: AiSuiteConfirm | null = null
  await update($, pendingAtom, previous => {
    taken = previous
    return null
  })
  return taken
}

export function getCustomKey($: EngineInterface): Promise<string | null> {
  return read($, customKeyAtom)
}
export async function setCustomKey($: EngineInterface, key: string | null): Promise<void> {
  await update($, customKeyAtom, () => key)
}

export function getDetail($: EngineInterface): Promise<AiSuiteDetail | null> {
  return read($, detailAtom)
}
export async function setDetail($: EngineInterface, detail: AiSuiteDetail | null): Promise<void> {
  await update($, detailAtom, () => detail)
}

// ---------------------------------------------------------------- selections

/** Changes one list's ticked keys; the other list keeps its own. */
async function patchSelection(
  $: EngineInterface,
  list: SelectList,
  change: (keys: readonly string[]) => string[],
): Promise<void> {
  if (list === 'install') await update($, installSelectionAtom, keys => change(keys))
  else await update($, installedSelectionAtom, keys => change(keys))
}

export async function toggleSelected($: EngineInterface, list: SelectList, key: string): Promise<void> {
  await patchSelection($, list, keys => toggled(keys, key))
}

export async function addSelected($: EngineInterface, list: SelectList, keys: readonly string[]): Promise<void> {
  await patchSelection($, list, previous => merged(previous, keys))
}

export async function dropSelected($: EngineInterface, list: SelectList, keys: readonly string[]): Promise<void> {
  await patchSelection($, list, previous => without(previous, keys))
}

export async function clearSelected($: EngineInterface, list: SelectList): Promise<void> {
  await patchSelection($, list, () => [])
}

/** After a rescan: forgets the ticked keys that no longer name a skill the list can tick. */
export async function pruneSelections($: EngineInterface, rows: readonly AiSuiteSkillRow[]): Promise<void> {
  await patchSelection($, 'install', keys => keepKnown(keys, rows, 'install'))
  await patchSelection($, 'installed', keys => keepKnown(keys, rows, 'installed'))
}

export async function setMessage(
  $: EngineInterface,
  kind: AiSuiteMessage['kind'],
  text: string,
): Promise<void> {
  await update($, messageAtom, () => ({ kind, text }))
}

export async function clearMessage($: EngineInterface): Promise<void> {
  await update($, messageAtom, () => null)
}

export async function setBandHidden($: EngineInterface, isHidden: boolean): Promise<void> {
  await update($, bandHiddenAtom, () => isHidden)
}

/** Remembers whether the pane opened by `$.ui.open` is waiting undrawn (`isPlaced: false`). */
export async function setPaneWaiting($: EngineInterface, isWaiting: boolean): Promise<void> {
  await update($, paneWaitingAtom, () => isWaiting)
}

// ---------------------------------------------------------------- the pane's data

/** Everything the pane draws from, read in one go so the drawing stays a pure function of it. */
export type PaneData = {
  view: AiSuiteView
  pages: Record<string, number>
  filters: AiSuiteFilters
  pending: AiSuiteConfirm | null
  busy: AiSuiteBusy | null
  message: AiSuiteMessage | null
  customKey: string | null
  detail: AiSuiteDetail | null
  installSelection: string[]
  installedSelection: string[]
  repo: AiSuiteRepo | null
  snapshots: AiSuiteSnapshots
}

export async function readPane($: EngineInterface): Promise<PaneData> {
  const [view, pages, filters, pending, busy, message, customKey, detail, installSelection, installedSelection, repo, snapshots] =
    await Promise.all([
      read($, viewAtom),
      read($, pagesAtom),
      read($, filtersAtom),
      read($, pendingAtom),
      read($, busyAtom),
      read($, messageAtom),
      read($, customKeyAtom),
      read($, detailAtom),
      read($, installSelectionAtom),
      read($, installedSelectionAtom),
      read($, repoAtom),
      read($, snapshotsAtom),
    ])
  return {
    view,
    pages,
    filters,
    pending,
    busy,
    message,
    customKey,
    detail,
    installSelection,
    installedSelection,
    repo,
    snapshots,
  }
}

/** What the band above the prompt draws from, read in one go (and so subscribing the drawing). */
export type BandData = {
  isHidden: boolean
  isPaneWaiting: boolean
  repoError: string
  status: AiSuiteSnapshot<AiSuiteSkillRow[]>
  updates: AiSuiteSnapshot<AiSuiteUpdates>
}

export async function readBand($: EngineInterface): Promise<BandData> {
  const [isHidden, isPaneWaiting, repo, snapshots] = await Promise.all([
    read($, bandHiddenAtom),
    read($, paneWaitingAtom),
    read($, repoAtom),
    read($, snapshotsAtom),
  ])
  return {
    isHidden,
    isPaneWaiting,
    repoError: repo?.error ?? '',
    status: snapshots.status,
    updates: snapshots.updates,
  }
}
