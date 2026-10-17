// Every $.state value the mod keeps, and the only place that touches them. The
// scan behind `claude plugin validate` follows an atom only inside the module
// that declares it, so each atom has its accessors right here and the rest of
// the mod calls those. Reads made while a ui.render hook draws subscribe the
// drawing, so a write redraws the pane by itself.
import { atom, read, update } from 'claude-code'
import type { EngineInterface } from 'claude-code'
import type {
  AiSuiteBusy,
  AiSuiteMessage,
  AiSuiteRepo,
  AiSuiteSnapshot,
  AiSuiteSnapshots,
  AiSuiteView,
} from '../types'

export const PANE_ID = 'ai-suite'

export const VIEWS: readonly { id: AiSuiteView; label: string; hotkey: string }[] = [
  { id: 'overview', label: 'Overview', hotkey: 'o' },
  { id: 'install', label: 'Install', hotkey: 'i' },
  { id: 'issues', label: 'Issues', hotkey: 's' },
  { id: 'updates', label: 'Updates', hotkey: 'u' },
  { id: 'workflows', label: 'Workflows', hotkey: 'w' },
  { id: 'doctor', label: 'Doctor', hotkey: 'd' },
]

export type SnapshotName = keyof AiSuiteSnapshots

export function emptySnapshot<T>(): AiSuiteSnapshot<T> {
  return { data: null, fetchedAt: null, error: null }
}

function emptySnapshots(): AiSuiteSnapshots {
  return {
    status: emptySnapshot(),
    catalog: emptySnapshot(),
    issues: emptySnapshot(),
    updates: emptySnapshot(),
    workflows: emptySnapshot(),
    doctor: emptySnapshot(),
  }
}

const viewAtom = atom({ plugin: 'ai-suite', key: 'view' } as const, 'overview')
const pageAtom = atom({ plugin: 'ai-suite', key: 'page' } as const, 0)
const repoAtom = atom({ plugin: 'ai-suite', key: 'repo' } as const, null)
const snapshotsAtom = atom({ plugin: 'ai-suite', key: 'snapshots' } as const, emptySnapshots())
const busyAtom = atom({ plugin: 'ai-suite', key: 'busy' } as const, null)
const pendingAtom = atom({ plugin: 'ai-suite', key: 'pendingConfirm' } as const, null)
const messageAtom = atom({ plugin: 'ai-suite', key: 'message' } as const, null)

// ---------------------------------------------------------------- accessors

export function getView($: EngineInterface): Promise<AiSuiteView> {
  return read($, viewAtom)
}
export async function setView($: EngineInterface, view: AiSuiteView): Promise<void> {
  await update($, viewAtom, () => view)
}

export async function setPage($: EngineInterface, page: number): Promise<void> {
  await update($, pageAtom, () => Math.max(0, page))
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

export async function setPending($: EngineInterface, key: string | null): Promise<void> {
  await update($, pendingAtom, () => key)
}

/** Disarms the confirm and says whether `key` was the armed one, in a single read-and-write. */
export async function takePending($: EngineInterface, key: string): Promise<boolean> {
  let wasArmed = false
  await update($, pendingAtom, previous => {
    wasArmed = previous === key
    return null
  })
  return wasArmed
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

// ---------------------------------------------------------------- the pane's data

/** Everything the pane draws from, read in one go so the drawing stays a pure function of it. */
export type PaneData = {
  view: AiSuiteView
  page: number
  pending: string | null
  busy: AiSuiteBusy | null
  message: AiSuiteMessage | null
  repo: AiSuiteRepo | null
  snapshots: AiSuiteSnapshots
}

export async function readPane($: EngineInterface): Promise<PaneData> {
  const [view, page, pending, busy, message, repo, snapshots] = await Promise.all([
    read($, viewAtom),
    read($, pageAtom),
    read($, pendingAtom),
    read($, busyAtom),
    read($, messageAtom),
    read($, repoAtom),
    read($, snapshotsAtom),
  ])
  return { view, page, pending, busy, message, repo, snapshots }
}
