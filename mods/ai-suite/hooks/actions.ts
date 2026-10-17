// What the pane does: the two-press confirm, switching views, and the mutating
// commands behind the buttons, plus the session-level checks. Every failure
// lands in the message atom and a toast; nothing here throws or runs on a timer.
import type { EngineInterface } from 'claude-code'
import type { AiSuiteChanged, AiSuiteView } from '../types'
import { errText, notableLines, runCli, truncate } from './cli'
import type { Settings } from './cli'
import {
  APPLY_MS,
  DOCTOR,
  SLOW_MS,
  STATUS,
  UPDATES,
  UPDATES_FETCH,
  fail,
  invalidateAll,
  isStale,
  load,
  refreshStatusLine,
  refreshView,
  resolveCfg,
  withBusy,
} from './load'
import {
  PANE_ID,
  clearMessage,
  getRepo,
  getSnapshots,
  getView,
  setMessage,
  setPage,
  setPending,
  setView,
  takePending,
} from './state'
import { checkSummary } from './summary'

export type Named = { scope: string; name: string }

/** What a button does, as data: the pane's tree holds no `$`, so the hook runs it. */
export type Command =
  | { kind: 'view'; view: AiSuiteView }
  | { kind: 'refresh'; view: AiSuiteView }
  | { kind: 'page'; page: number }
  | { kind: 'install'; row: Named }
  | { kind: 'install-all' }
  | { kind: 'relink'; row: Named }
  | { kind: 'retire'; row: Named }
  | { kind: 'apply' }
  | { kind: 'fetch' }
  | { kind: 'pull' }
  | { kind: 'update-changed' }

export type Act = {
  key: string
  label: string
  command: Command
  hotkey?: string
  /** When set the button arms on its first press (showing this text) and runs on its second. */
  confirm?: string
  isPrimary?: boolean
}

type Step = { args: string[]; timeoutMs: number }

const step = (args: string[], timeoutMs = SLOW_MS): Step => ({ args, timeoutMs })

const idOf = (row: Named): string => `${row.scope}/${row.name}`

function byScope(items: readonly Named[]): [string, string[]][] {
  const scopes = [...new Set(items.map(item => item.scope))]
  return scopes.map(scope => [scope, items.filter(item => item.scope === scope).map(item => item.name)])
}

// ----------------------------------------------------------- views and paging

async function loadFor(
  $: EngineInterface,
  settings: Settings,
  label: string,
  view: AiSuiteView,
  isForced: boolean,
): Promise<void> {
  if (!isForced && !(await isStale($, view))) return
  await withBusy($, label, async () => {
    const cfg = await resolveCfg($, settings, false)
    if (cfg !== null) await refreshView($, cfg, view, isForced)
  })
  await refreshStatusLine($)
}

async function openView($: EngineInterface, settings: Settings, view: AiSuiteView): Promise<void> {
  await setView($, view)
  await setPage($, 0)
  await clearMessage($)
  await loadFor($, settings, `Loading ${view}`, view, false)
}

/** `/skills`: open the pane, then fill whatever the current view is missing. */
export async function openPane($: EngineInterface, settings: Settings): Promise<string> {
  const opened = await $.ui.open({ id: PANE_ID, title: 'Skills', focus: true, closeOnEscape: true })
  await loadFor($, settings, 'Loading', await getView($), false)
  return opened.isPlaced ? 'Skills pane opened.' : `Skills pane is waiting: ${opened.reason}`
}

// ----------------------------------------------------------------- mutations

/** Runs the steps in order, stops at the first failure, and on success re-reads what the pane shows. */
async function mutate(
  $: EngineInterface,
  settings: Settings,
  view: AiSuiteView,
  label: string,
  steps: readonly Step[],
  done: string,
): Promise<void> {
  await withBusy($, label, async () => {
    const cfg = await resolveCfg($, settings, false)
    if (cfg === null) return
    const notes: string[] = []
    let didSomething = false
    for (const next of steps) {
      const out = await runCli($, cfg, next.args, { timeoutMs: next.timeoutMs })
      if (!out.ok) {
        await fail($, `${label} failed: ${out.error}`)
        return
      }
      didSomething = didSomething || !/^Nothing to do\.$/m.test(out.stdout)
      notes.push(...notableLines(out.stdout, cfg.home))
    }
    await invalidateAll($)
    await setMessage(
      $,
      didSomething ? 'ok' : 'info',
      truncate([didSomething ? done : 'Nothing to do.', ...notes].join(' · '), 400),
    )
    if (await refreshView($, cfg, view, false)) await refreshView($, cfg, 'overview', false)
  })
  await refreshStatusLine($)
}

async function installAllMissing($: EngineInterface, settings: Settings): Promise<void> {
  const { catalog } = await getSnapshots($)
  const missing = (catalog.data ?? []).filter(row => row.state === 'not-installed')
  if (missing.length === 0) {
    await setMessage($, 'info', 'Nothing to install.')
    return
  }
  const steps = byScope(missing).map(([scope, names]) => step(['install', ...names, '--scope', scope, '--yes']))
  await mutate($, settings, 'install', 'Install all missing', steps, `Installed ${missing.length} skills.`)
}

async function updateChanged($: EngineInterface, settings: Settings): Promise<void> {
  const { status, updates } = await getSnapshots($)
  const modified = new Set((status.data ?? []).filter(row => row.state === 'modified').map(idOf))
  const targets: AiSuiteChanged[] = (updates.data?.changed ?? []).filter(change => modified.has(idOf(change)))
  if (targets.length === 0) {
    await setMessage($, 'info', 'No modified skill has an upstream change.')
    return
  }
  const steps = byScope(targets).map(([scope, names]) => step(['update', ...names, '--scope', scope, '--yes']))
  await mutate($, settings, 'updates', 'Update changed', steps, `Updated ${targets.length} skills.`)
}

async function fetchUpdates($: EngineInterface, settings: Settings): Promise<void> {
  await withBusy($, 'Fetching', async () => {
    const cfg = await resolveCfg($, settings, false)
    if (cfg === null) return
    if ((await load($, cfg, UPDATES_FETCH, false)) === null) await setMessage($, 'ok', 'Fetched.')
  })
  await refreshStatusLine($)
}

async function perform($: EngineInterface, settings: Settings, command: Command): Promise<void> {
  switch (command.kind) {
    case 'view':
      return openView($, settings, command.view)
    case 'refresh':
      return loadFor($, settings, 'Refreshing', command.view, true)
    case 'page':
      await setPage($, command.page)
      return
    case 'install':
      return mutate($, settings, 'install', `Install ${idOf(command.row)}`,
        [step(['install', command.row.name, '--scope', command.row.scope, '--yes'])],
        `Installed ${idOf(command.row)}.`)
    case 'install-all':
      return installAllMissing($, settings)
    case 'relink':
      return mutate($, settings, 'issues', `Relink ${idOf(command.row)}`,
        [step(['relink', command.row.name, '--yes'])], `Relinked ${idOf(command.row)}.`)
    case 'retire':
      return mutate($, settings, 'issues', `Retire ${idOf(command.row)}`,
        [step(['retire', command.row.name, '--scope', command.row.scope, '--yes'])],
        `Retired ${idOf(command.row)} (moved to a backup).`)
    case 'apply':
      return mutate($, settings, 'overview', 'Apply config',
        [step(['apply', '--yes'], APPLY_MS)], 'Config applied.')
    case 'fetch':
      return fetchUpdates($, settings)
    case 'pull':
      return mutate($, settings, 'updates', 'Pull', [step(['pull', '--yes'])], 'Pulled (fast-forward only).')
    case 'update-changed':
      return updateChanged($, settings)
  }
}

/**
 * One button press. A button with a `confirm` text arms on its first press and
 * runs on its second; any other press (including another button's first) disarms it.
 */
export async function pressAct($: EngineInterface, settings: Settings, act: Act): Promise<void> {
  if (act.confirm === undefined) {
    await setPending($, null)
    await perform($, settings, act.command)
    return
  }
  if (await takePending($, act.key)) {
    await perform($, settings, act.command)
    return
  }
  await setPending($, act.key)
  await setMessage($, 'info', `${act.confirm} Press again to confirm.`)
}

// -------------------------------------------------------- session-level work

/** session.start's background check: status and updates without the network; never throws. */
export async function startupCheck($: EngineInterface, settings: Settings): Promise<void> {
  try {
    const cfg = await resolveCfg($, settings, true)
    if (cfg === null) {
      $.ui.status('skills: repo not found (open /skills)')
      return
    }
    if ((await load($, cfg, STATUS, true)) === null) await load($, cfg, UPDATES, true)
    await refreshStatusLine($)
  } catch (error) {
    try {
      $.ui.log(`ai-suite: the start check failed: ${errText(error)}`, { to: 'debug' })
    } catch {
      // nothing more can be done
    }
  }
}

/** `/skills-check`: doctor plus a fetching updates read, summarised in one line. */
export async function runCheck($: EngineInterface, settings: Settings): Promise<string> {
  const cfg = await resolveCfg($, settings, true)
  if (cfg === null) {
    const text = (await getRepo($))?.error || 'repo not found'
    $.ui.toast(text)
    return text
  }
  const doctorError = await load($, cfg, DOCTOR, true)
  const updatesError = await load($, cfg, UPDATES_FETCH, true)
  const { doctor, updates } = await getSnapshots($)
  await refreshStatusLine($)
  const text = checkSummary({
    doctor: doctorError === null ? doctor.data : null,
    doctorError,
    updates: updatesError === null ? updates.data : null,
    updatesError,
  })
  $.ui.toast(text)
  return text
}
