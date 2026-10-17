// The commands behind the pane's buttons that change something or run something worth
// showing: skills, the repo, the apply job, settings, file lists and previews. Every
// failure lands in the message atom and a toast; nothing here throws or runs on a timer.
import type { EngineInterface } from 'claude-code'
import type { AiSuiteScopeFilter } from '../types'
import { notableLines, runCli, truncate } from './cli'
import type { Cfg, Settings } from './cli'
import { idOf } from './commands'
import type { Named } from './commands'
import {
  APPLY_MS,
  CONFIG,
  SLOW_MS,
  UPDATES_FETCH,
  fail,
  invalidateAll,
  load,
  loadConfigFile,
  refreshStatusLine,
  refreshView,
  resolveCfg,
  withBusy,
} from './load'
import { settingLabel } from './presets'
import { getDetail, getSnapshots, getView, setCustomKey, setDetail, setMessage, setPage } from './state'
import { filterMissing, updatable } from './summary'

type Step = { args: string[]; timeoutMs: number }

/** After something changed on disk: every snapshot and the detail card under the view are stale. */
export async function forgetAll($: EngineInterface): Promise<void> {
  await invalidateAll($)
  await setDetail($, null)
}

/** Re-reads what the current view shows, and the Overview's numbers when that worked. */
export async function reread($: EngineInterface, cfg: Cfg): Promise<void> {
  if (await refreshView($, cfg, await getView($), false)) await refreshView($, cfg, 'overview', false)
}

const step = (args: string[], timeoutMs = SLOW_MS): Step => ({ args, timeoutMs })

function byScope(items: readonly Named[]): [string, string[]][] {
  const scopes = [...new Set(items.map(item => item.scope))]
  return scopes.map(scope => [scope, items.filter(item => item.scope === scope).map(item => item.name)])
}

/**
 * Runs the steps in order and stops at the first failure. On success it says so (message and
 * toast), re-reads what the current view shows and answers the steps' output, home-shortened;
 * on failure it answers null.
 */
async function mutate(
  $: EngineInterface,
  settings: Settings,
  label: string,
  steps: readonly Step[],
  done: string,
): Promise<string | null> {
  let output: string | null = null
  await withBusy($, label, async () => {
    const cfg = await resolveCfg($, settings, false)
    if (cfg === null) return
    const notes: string[] = []
    const printed: string[] = []
    let didSomething = false
    for (const next of steps) {
      const out = await runCli($, cfg, next.args, { timeoutMs: next.timeoutMs })
      if (!out.ok) {
        await fail($, `${label} failed: ${out.error}`)
        return
      }
      didSomething = didSomething || !/^Nothing to do\.$/m.test(out.stdout)
      notes.push(...notableLines(out.stdout, cfg.home))
      printed.push(cfg.home === '' ? out.stdout : out.stdout.split(cfg.home).join('~'))
    }
    await forgetAll($)
    const headline = didSomething ? done : 'Nothing to do.'
    await setMessage($, didSomething ? 'ok' : 'info', truncate([headline, ...notes].join(' · '), 400))
    $.ui.toast(headline)
    await reread($, cfg)
    output = printed.join('\n')
  })
  await refreshStatusLine($)
  return output
}

// -------------------------------------------------------------------- skills

export async function installOne($: EngineInterface, settings: Settings, row: Named): Promise<void> {
  const args = ['install', row.name, '--scope', row.scope, '--yes']
  await mutate($, settings, `Install ${idOf(row)}`, [step(args)], `Installed ${idOf(row)}.`)
}

export async function updateOne($: EngineInterface, settings: Settings, row: Named): Promise<void> {
  const args = ['update', row.name, '--scope', row.scope, '--yes']
  await mutate($, settings, `Update ${idOf(row)}`, [step(args)], `Updated ${idOf(row)}.`)
}

export async function relinkOne($: EngineInterface, settings: Settings, row: Named): Promise<void> {
  await mutate($, settings, `Relink ${idOf(row)}`, [step(['relink', row.name, '--yes'])], `Relinked ${idOf(row)}.`)
}

export async function retireOne($: EngineInterface, settings: Settings, row: Named): Promise<void> {
  const args = ['retire', row.name, '--scope', row.scope, '--yes']
  await mutate($, settings, `Retire ${idOf(row)}`, [step(args)], `Retired ${idOf(row)} (moved to a backup).`)
}

/** Installs every missing skill the Install view's filters name (all of them for scope `all`, tag `all` and no query). */
export async function installAll(
  $: EngineInterface,
  settings: Settings,
  scope: AiSuiteScopeFilter,
  query: string,
  tag: string,
): Promise<void> {
  const { status } = await getSnapshots($)
  const missing = filterMissing(status.data ?? [], { installScope: scope, installQuery: query, installTag: tag })
  if (missing.length === 0) {
    await setMessage($, 'info', 'Nothing to install.')
    return
  }
  const steps = byScope(missing).map(([at, names]) => step(['install', ...names, '--scope', at, '--yes']))
  await mutate($, settings, 'Install all missing', steps, `Installed ${missing.length} skills.`)
}

export async function updateChanged($: EngineInterface, settings: Settings): Promise<void> {
  const { status, updates } = await getSnapshots($)
  const targets = updatable(status.data ?? [], updates.data)
  if (targets.length === 0) {
    await setMessage($, 'info', 'No modified skill has an upstream change.')
    return
  }
  const steps = byScope(targets).map(([at, names]) => step(['update', ...names, '--scope', at, '--yes']))
  await mutate($, settings, 'Update changed', steps, `Updated ${targets.length} skills.`)
}

// ---------------------------------------------------------------------- repo

export async function fetchUpdates($: EngineInterface, settings: Settings): Promise<void> {
  await withBusy($, 'Fetching', async () => {
    const cfg = await resolveCfg($, settings, false)
    if (cfg === null) return
    if ((await load($, cfg, UPDATES_FETCH, false)) === null) {
      await setMessage($, 'ok', 'Fetched.')
      $.ui.toast('Fetched')
    }
  })
  await refreshStatusLine($)
}

export async function pullRepo($: EngineInterface, settings: Settings): Promise<void> {
  await mutate($, settings, 'Pull', [step(['pull', '--yes'])], 'Pulled (fast-forward only).')
}

/** The apply job; its output stays in a card under Settings until the view changes. */
export async function applyConfig($: EngineInterface, settings: Settings): Promise<void> {
  const output = await mutate($, settings, 'Apply config', [step(['apply', '--yes'], APPLY_MS)], 'Config applied.')
  if (output !== null) await setDetail($, { kind: 'apply', id: 'apply', text: output.trim() })
}

export async function workflowAct(
  $: EngineInterface,
  settings: Settings,
  verb: 'retire' | 'push',
  name: string,
): Promise<void> {
  const done = verb === 'retire' ? `Retired workflow ${name} (moved to a backup).` : `Pushed workflow ${name} to the repo.`
  await mutate($, settings, `Workflow ${verb} ${name}`, [step(['workflow', verb, name, '--yes'])], done)
}

// --------------------------------------------------------------- text details

/** Shows (or, pressed again, hides) a card with the text a read-only command prints. */
export async function showDetail(
  $: EngineInterface,
  settings: Settings,
  kind: 'files' | 'preview',
  id: string,
  args: string[],
): Promise<void> {
  const current = await getDetail($)
  if (current !== null && current.kind === kind && current.id === id) {
    await setDetail($, null)
    return
  }
  await withBusy($, `${kind === 'files' ? 'Listing' : 'Rendering'} ${id}`, async () => {
    const cfg = await resolveCfg($, settings, false)
    if (cfg === null) return
    const out = await runCli($, cfg, args, { timeoutMs: SLOW_MS })
    if (!out.ok) {
      await fail($, `${args.join(' ')} failed: ${out.error}`)
      return
    }
    const text = cfg.home === '' ? out.stdout : out.stdout.split(cfg.home).join('~')
    await setPage($, 'preview', 0)
    await setDetail($, { kind, id, text: text.trimEnd() })
  })
}

// ------------------------------------------------------------------ settings

/** Re-reads the settings snapshots after a write; a failed read leaves the old values in place. */
async function rereadConfig($: EngineInterface, settings: Settings): Promise<void> {
  const cfg = await resolveCfg($, settings, true)
  if (cfg === null) return
  await load($, cfg, CONFIG, true)
  await loadConfigFile($, cfg, true)
}

async function writeSetting(
  $: EngineInterface,
  settings: Settings,
  label: string,
  steps: readonly Step[],
  toast: string,
): Promise<void> {
  await withBusy($, label, async () => {
    const cfg = await resolveCfg($, settings, false)
    if (cfg === null) return
    for (const next of steps) {
      const out = await runCli($, cfg, next.args, { timeoutMs: next.timeoutMs })
      if (!out.ok) {
        await fail($, `${label} failed: ${out.error}`)
        return
      }
    }
    await setCustomKey($, null)
    await rereadConfig($, settings)
    $.ui.toast(toast)
  })
}

/** `config set KEY VALUE`: one setting, written at once; the values are re-read afterwards. */
export async function saveSetting(
  $: EngineInterface,
  settings: Settings,
  key: string,
  value: string,
): Promise<void> {
  const label = settingLabel(key)
  await writeSetting($, settings, `Save ${label}`, [step(['config', 'set', key, value, '--yes'])], `Saved ${label}`)
}

export async function resetSetting($: EngineInterface, settings: Settings, key: string): Promise<void> {
  const label = settingLabel(key)
  await writeSetting($, settings, `Reset ${label}`, [step(['config', 'reset', key, '--yes'])], `Saved ${label} (reset)`)
}

/**
 * Writes config.json with the defaults. A set to the value already in force writes nothing, so the
 * file is made by changing one harmless setting and putting it back.
 */
export async function createConfig($: EngineInterface, settings: Settings): Promise<void> {
  const steps = [step(['config', 'set', 'editor', 'nano', '--yes']), step(['config', 'reset', 'editor', '--yes'])]
  await writeSetting($, settings, 'Create config', steps, 'Saved config.json with the defaults')
}
