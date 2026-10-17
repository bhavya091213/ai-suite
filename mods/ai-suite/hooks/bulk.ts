// What the selection bar's buttons run: one installer call per scope, in order, stopping at the
// first failure. When every call worked the list's selection is cleared; when one failed, the
// skills that were done leave the selection (the rest stay ticked) and the failure says how many
// of them were. Every failure lands in the message atom and a toast; nothing here throws.
import type { EngineInterface } from 'claude-code'
import { notableLines, runCli, truncate } from './cli'
import type { Cfg, Settings } from './cli'
import type { BulkVerb, SelectList } from './commands'
import { SLOW_MS, fail, refreshStatusLine, resolveCfg, withBusy } from './load'
import { forgetAll, reread } from './mutations'
import { groupByScope, skillsOf } from './selection'
import type { Group } from './selection'
import { clearSelected, dropSelected, setMessage } from './state'

type Verb = {
  label: string
  /** What the success line says it did (`Retired 3 skills (moved to a backup).`). */
  done: (count: number) => string
  args: (group: Group) => string[]
}

const VERBS: Record<BulkVerb, Verb> = {
  install: {
    label: 'Install',
    done: count => `Installed ${skillsOf(count)}.`,
    args: group => ['install', ...group.names, '--scope', group.scope, '--yes'],
  },
  update: {
    label: 'Update',
    done: count => `Updated ${skillsOf(count)}.`,
    args: group => ['update', ...group.names, '--scope', group.scope, '--yes'],
  },
  relink: {
    label: 'Relink',
    done: count => `Relinked ${skillsOf(count)}.`,
    args: group => ['relink', ...group.names, '--yes'],
  },
  retire: {
    label: 'Retire',
    done: count => `Retired ${skillsOf(count)} (moved to a backup).`,
    args: group => ['retire', ...group.names, '--scope', group.scope, '--yes'],
  },
}

/** A call failed after `done` skills were handled: they leave the selection, the view is re-read, the failure is said. */
async function stopAt(
  $: EngineInterface,
  cfg: Cfg,
  list: SelectList,
  label: string,
  done: readonly string[],
  total: number,
  error: string,
): Promise<void> {
  if (done.length > 0) {
    await dropSelected($, list, done)
    await forgetAll($)
    await reread($, cfg)
  }
  await fail($, `${label} failed: ${error} (${done.length} of ${total} done)`)
}

/** Runs `verb` on the ticked skills `keys` (`scope/name`) of `list`. */
export async function bulkRun(
  $: EngineInterface,
  settings: Settings,
  list: SelectList,
  verb: BulkVerb,
  keys: readonly string[],
): Promise<void> {
  const groups = groupByScope(keys)
  const total = groups.reduce((sum, group) => sum + group.names.length, 0)
  const spec = VERBS[verb]
  if (total === 0) {
    await setMessage($, 'info', `Nothing to ${spec.label.toLowerCase()}.`)
    return
  }
  const label = `${spec.label} ${skillsOf(total)}`
  await withBusy($, label, async () => {
    const cfg = await resolveCfg($, settings, false)
    if (cfg === null) return
    const done: string[] = []
    const notes: string[] = []
    for (const group of groups) {
      const out = await runCli($, cfg, spec.args(group), { timeoutMs: SLOW_MS })
      if (!out.ok) {
        await stopAt($, cfg, list, label, done, total, out.error)
        return
      }
      done.push(...group.names.map(name => `${group.scope}/${name}`))
      notes.push(...notableLines(out.stdout, cfg.home))
    }
    await clearSelected($, list)
    await forgetAll($)
    const headline = spec.done(total)
    await setMessage($, 'ok', truncate([headline, ...notes].join(' · '), 400))
    $.ui.toast(headline)
    await reread($, cfg)
  })
  await refreshStatusLine($)
}
