// Loading and bookkeeping under the pane: reading each command into its
// snapshot, the busy flag, repo resolution, failures and the status line.
import type { EngineInterface } from 'claude-code'
import type { AiSuiteView } from '../types'
import { errText, resolveRepo, runCli, runJson, truncate } from './cli'
import type { Cfg, RunOptions, Settings } from './cli'
import {
  parseCaps,
  parseConfig,
  parseDoctor,
  parseStatus,
  parseUpdates,
  parseWorkflows,
} from './parse'
import {
  getBusy,
  getSnapshots,
  patchSnapshot,
  pruneSelections,
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
  if (result.ok) {
    // a rescan of the skills drops the ticked ones that no longer exist
    if (spec.name === 'status') await pruneSelections($, (await getSnapshots($)).status.data ?? [])
    return null
  }
  if (!isQuiet) await fail($, `${spec.label} failed: ${result.error}`)
  return result.error
}

export const STATUS: LoadSpec = {
  name: 'status',
  label: 'status',
  args: ['status', '--json'],
  parse: parseStatus,
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
export const DOCTOR: LoadSpec = {
  name: 'doctor',
  label: 'doctor',
  args: ['doctor', '--json'],
  parse: parseDoctor,
  options: { accept: [0, 1] },
}
export const CONFIG: LoadSpec = {
  name: 'config',
  label: 'config list',
  args: ['config', 'list', '--json'],
  parse: parseConfig,
}
const WORKFLOWS: LoadSpec = {
  name: 'workflows',
  label: 'workflow list',
  args: ['workflow', 'list', '--json'],
  parse: parseWorkflows,
}
const CAPS: LoadSpec = {
  name: 'caps',
  label: 'caps',
  args: ['caps', '--json'],
  parse: parseCaps,
}

/** Reads `config path`, then asks the file system whether config.json is there yet. */
export async function loadConfigFile($: EngineInterface, cfg: Cfg, isQuiet: boolean): Promise<string | null> {
  const out = await runCli($, cfg, ['config', 'path'])
  const path = out.ok ? (out.stdout.split('\n')[0] ?? '').trim() : ''
  let exists = false
  if (path !== '') {
    try {
      exists = await $.fs.exists(path)
    } catch {
      exists = false
    }
  }
  const error = out.ok ? (path === '' ? 'config path: no path printed' : null) : out.error
  const now = await $.clock.now()
  await patchSnapshot($, 'configFile', previous =>
    error === null
      ? { data: { path, exists }, fetchedAt: now, error: null }
      : { ...previous, error },
  )
  if (error !== null && !isQuiet) await fail($, `config path failed: ${error}`)
  return error
}

/** Loads one snapshot by name; returns the error text, or null on success. */
async function loadSnapshot(
  $: EngineInterface,
  cfg: Cfg,
  name: SnapshotName,
  isQuiet: boolean,
): Promise<string | null> {
  const specs: Record<Exclude<SnapshotName, 'configFile'>, LoadSpec> = {
    status: STATUS,
    updates: UPDATES,
    workflows: WORKFLOWS,
    doctor: DOCTOR,
    caps: CAPS,
    config: CONFIG,
  }
  return name === 'configFile'
    ? loadConfigFile($, cfg, isQuiet)
    : load($, cfg, specs[name], isQuiet)
}

/** What each view reads, in order: a view is stale while any of these has neither data nor an error. */
const SOURCES: Record<AiSuiteView, readonly SnapshotName[]> = {
  overview: ['status', 'updates', 'configFile'],
  install: ['status'],
  installed: ['status'],
  updates: ['updates', 'status'],
  settings: ['configFile', 'config', 'caps'],
  workflows: ['workflows'],
  doctor: ['doctor', 'caps'],
}

export async function isStale($: EngineInterface, view: AiSuiteView): Promise<boolean> {
  const all = await getSnapshots($)
  return SOURCES[view].some(name => all[name].data === null && all[name].error === null)
}

/** Loads what a view shows; stops at the first failure. `isForced` re-reads what is already there. */
export async function refreshView(
  $: EngineInterface,
  cfg: Cfg,
  view: AiSuiteView,
  isForced: boolean,
): Promise<boolean> {
  for (const name of SOURCES[view]) {
    const known = (await getSnapshots($))[name]
    if (!isForced && (known.data !== null || known.error !== null)) continue
    if ((await loadSnapshot($, cfg, name, false)) !== null) return false
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
      ? { path: found.repo, shown: found.shown, home: found.home, error: '' }
      : { path: '', shown: '', home: '', error: found.error },
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
