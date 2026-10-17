// Loading and bookkeeping under the pane: reading each command into its
// snapshot, the busy flag, repo resolution, failures and the status line.
import type { EngineInterface } from 'claude-code'
import type { AiSuiteView } from '../types'
import {
  errText,
  parseCatalog,
  parseDoctor,
  parseIssues,
  parseStatus,
  parseUpdates,
  parseWorkflows,
  resolveRepo,
  runJson,
  truncate,
} from './cli'
import type { Cfg, RunOptions, Settings } from './cli'
import {
  getBusy,
  getSnapshots,
  patchSnapshot,
  resetSnapshots,
  setBusy,
  setMessage,
  setRepo,
} from './state'
import type { SnapshotName } from './state'
import { statusLineText } from './summary'

export const BUSY_TTL_MS = 600_000
export const SLOW_MS = 120_000
export const APPLY_MS = 300_000
export const FETCH_MS = 90_000

export async function fail($: EngineInterface, text: string): Promise<void> {
  await setMessage($, 'error', text)
  $.ui.toast(text)
}

// ------------------------------------------------------------------- loading

/** One read command and the snapshot it fills. `parse` answers null for a JSON shape it does not know. */
export type LoadSpec = {
  name: SnapshotName
  label: string
  args: readonly string[]
  parse: (raw: unknown) => unknown
  options?: RunOptions
}

/** Runs one read command into its snapshot; returns the error text, or null on success. */
export async function load(
  $: EngineInterface,
  cfg: Cfg,
  spec: LoadSpec,
  isQuiet: boolean,
): Promise<string | null> {
  const result = await runJson($, cfg, spec.args, spec.parse, spec.options)
  const now = await $.clock.now()
  await patchSnapshot($, spec.name, previous =>
    result.ok
      ? { data: result.data, fetchedAt: now, error: null }
      : { ...previous, error: result.error },
  )
  if (result.ok) return null
  if (!isQuiet) await fail($, `${spec.label} failed: ${result.error}`)
  return result.error
}

export const STATUS: LoadSpec = {
  name: 'status',
  label: 'status',
  args: ['status', '--json'],
  parse: parseStatus,
}
const CATALOG: LoadSpec = {
  name: 'catalog',
  label: 'list',
  args: ['list', '--json'],
  parse: parseCatalog,
}
const ISSUES: LoadSpec = {
  name: 'issues',
  label: 'issues',
  args: ['issues', '--json'],
  parse: parseIssues,
}
export const UPDATES: LoadSpec = {
  name: 'updates',
  label: 'updates',
  args: ['updates', '--json'],
  parse: parseUpdates,
  options: { accept: [0, 1] },
}
export const UPDATES_FETCH: LoadSpec = {
  ...UPDATES,
  args: ['updates', '--json', '--fetch'],
  options: { accept: [0, 1], timeoutMs: FETCH_MS },
}
const WORKFLOWS: LoadSpec = {
  name: 'workflows',
  label: 'workflow list',
  args: ['workflow', 'list', '--json'],
  parse: parseWorkflows,
}
export const DOCTOR: LoadSpec = {
  name: 'doctor',
  label: 'doctor',
  args: ['doctor', '--json'],
  parse: parseDoctor,
  options: { accept: [0, 1] },
}

const SOURCES: Record<AiSuiteView, readonly LoadSpec[]> = {
  overview: [STATUS, UPDATES],
  install: [CATALOG],
  issues: [ISSUES],
  updates: [UPDATES, STATUS],
  workflows: [WORKFLOWS],
  doctor: [DOCTOR],
}

export async function isStale($: EngineInterface, view: AiSuiteView): Promise<boolean> {
  const all = await getSnapshots($)
  return SOURCES[view].some(spec => all[spec.name].data === null && all[spec.name].error === null)
}

/** Loads what a view shows; stops at the first failure. `isForced` re-reads what is already there. */
export async function refreshView(
  $: EngineInterface,
  cfg: Cfg,
  view: AiSuiteView,
  isForced: boolean,
): Promise<boolean> {
  for (const spec of SOURCES[view]) {
    const known = (await getSnapshots($))[spec.name]
    if (!isForced && (known.data !== null || known.error !== null)) continue
    if ((await load($, cfg, spec, false)) !== null) return false
  }
  return true
}

export async function invalidateAll($: EngineInterface): Promise<void> {
  await resetSnapshots($)
}

// ------------------------------------------------------------ repo and busy

/** Resolves the repo and records the outcome; null (and a toast unless quiet) when it is not found. */
export async function resolveCfg(
  $: EngineInterface,
  settings: Settings,
  isQuiet: boolean,
): Promise<Cfg | null> {
  const found = await resolveRepo($, settings)
  await setRepo(
    $,
    found.ok
      ? { path: found.repo, shown: found.shown, error: '' }
      : { path: '', shown: '', error: found.error },
  )
  if (found.ok) return { repo: found.repo, python: settings.python, home: found.home }
  if (!isQuiet) await fail($, found.error)
  return null
}

/** Runs `work` unless another command is in flight (a flag ten minutes old is ignored). */
export async function withBusy(
  $: EngineInterface,
  label: string,
  work: () => Promise<void>,
): Promise<void> {
  const now = await $.clock.now()
  const current = await getBusy($)
  if (current !== null && now - current.since < BUSY_TTL_MS) {
    await setMessage($, 'info', `Busy: ${current.label}. Try again when it finishes.`)
    return
  }
  await setBusy($, { label, since: now })
  try {
    await work()
  } catch (error) {
    await fail($, `${label} failed: ${truncate(errText(error), 200)}`)
  } finally {
    await setBusy($, null)
  }
}

export async function refreshStatusLine($: EngineInterface): Promise<void> {
  const { status, updates } = await getSnapshots($)
  const text = statusLineText(status, updates)
  if (text !== undefined) $.ui.status(text)
}
