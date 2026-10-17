// What the pane does when a control is used: the confirm card's rule, switching views,
// filters and pages, and the hand-off to mutations.ts, plus the session-level checks.
// Every failure lands in the message atom and a toast; nothing here throws or runs on a timer.
import type { EngineInterface } from 'claude-code'
import type { AiSuiteInstalledFilter, AiSuiteView } from '../types'
import { errText } from './cli'
import type { Settings } from './cli'
import { decodeConfirm, encodeConfirm, idOf } from './commands'
import type { Act, Command } from './commands'
import {
  DOCTOR,
  STATUS,
  UPDATES,
  UPDATES_FETCH,
  isStale,
  load,
  refreshStatusLine,
  refreshView,
  resolveCfg,
  withBusy,
} from './load'
import {
  applyConfig,
  createConfig,
  fetchUpdates,
  installAll,
  installOne,
  pullRepo,
  relinkOne,
  resetSetting,
  retireOne,
  saveSetting,
  showDetail,
  updateChanged,
  updateOne,
  workflowAct,
} from './mutations'
import {
  PANE_ID,
  clearMessage,
  getPending,
  getRepo,
  getSnapshots,
  getView,
  patchFilters,
  resetPages,
  setCustomKey,
  setDetail,
  setPage,
  setPaneWaiting,
  setPending,
  setView,
  takePending,
} from './state'
import { checkSummary } from './summary'

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

async function openView(
  $: EngineInterface,
  settings: Settings,
  view: AiSuiteView,
  installed: AiSuiteInstalledFilter | undefined,
): Promise<void> {
  await setView($, view)
  await resetPages($)
  await setDetail($, null)
  await setCustomKey($, null)
  await clearMessage($)
  if (installed !== undefined) await patchFilters($, { installed, installedTag: 'all' })
  await loadFor($, settings, `Loading ${view}`, view, false)
}

/** `/skills`: open the pane, then fill whatever the current view is missing. */
export async function openPane($: EngineInterface, settings: Settings): Promise<string> {
  const opened = await $.ui.open({ id: PANE_ID, title: 'Skills', focus: true, closeOnEscape: true })
  await setPaneWaiting($, !opened.isPlaced)
  await setPending($, null)
  await loadFor($, settings, 'Loading', await getView($), false)
  return opened.isPlaced ? 'Skills pane opened.' : `Skills pane is waiting: ${opened.reason}`
}

/**
 * session.start's own open: no `focus`, so it never takes the keyboard. On a terminal too narrow
 * for an unasked pane it waits undrawn; that is remembered so the band says how to seat it.
 * Never throws.
 */
export async function autoOpenPane($: EngineInterface): Promise<void> {
  try {
    const opened = await $.ui.open({ id: PANE_ID, title: 'Skills' })
    await setPaneWaiting($, !opened.isPlaced)
  } catch (error) {
    try {
      $.ui.log(`ai-suite: the pane did not open at start: ${errText(error)}`, { to: 'debug' })
    } catch {
      // nothing more can be done
    }
  }
}

// ------------------------------------------------------------------- pressing

async function perform($: EngineInterface, settings: Settings, command: Command): Promise<void> {
  switch (command.kind) {
    case 'view':
      return openView($, settings, command.view, command.installed)
    case 'refresh':
      return loadFor($, settings, 'Refreshing', await getView($), true)
    case 'page':
      return setPage($, command.list, command.page)
    case 'scope':
      await patchFilters($, { installScope: command.value })
      return setPage($, 'install', 0)
    case 'state':
      await patchFilters($, { installed: command.value })
      return setPage($, 'installed', 0)
    case 'query':
      await patchFilters($, { installQuery: command.text })
      return setPage($, 'install', 0)
    case 'tag':
      await patchFilters($, command.list === 'install'
        ? { installTag: command.value }
        : { installedTag: command.value })
      return setPage($, command.list, 0)
    case 'install':
      return installOne($, settings, command.row)
    case 'install-all':
      return installAll($, settings, command.scope, command.query, command.tag)
    case 'update':
      return updateOne($, settings, command.row)
    case 'update-changed':
      return updateChanged($, settings)
    case 'relink':
      return relinkOne($, settings, command.row)
    case 'retire':
      return retireOne($, settings, command.row)
    case 'files':
      return showDetail($, settings, 'files', idOf(command.row), ['tree', command.row.name, '--scope', command.row.scope])
    case 'close-detail':
      return setDetail($, null)
    case 'fetch':
      return fetchUpdates($, settings)
    case 'pull':
      return pullRepo($, settings)
    case 'apply':
      return applyConfig($, settings)
    case 'set':
      return saveSetting($, settings, command.key, command.value)
    case 'custom':
      return setCustomKey($, command.key)
    case 'reset':
      return resetSetting($, settings, command.key)
    case 'create-config':
      return createConfig($, settings)
    case 'preview':
      return showDetail($, settings, 'preview', command.name, ['workflow', 'render', command.name])
    case 'workflow-retire':
      return workflowAct($, settings, 'retire', command.name)
    case 'workflow-push':
      return workflowAct($, settings, 'push', command.name)
    case 'yes':
    case 'no':
      return
  }
}

/** Arms a confirm card and brings the top of the pane (where the card is drawn) into view. */
async function askConfirm($: EngineInterface, command: Command): Promise<void> {
  await setPending($, encodeConfirm(command))
  try {
    await $.ui.scroll({ to: 'start', in: PANE_ID })
  } catch {
    // the card is still drawn; only the scroll was refused
  }
}

/**
 * One press. While a confirm card is up only its Yes and No act and every other press is
 * ignored; Yes runs the command the card was armed with. An act marked `confirm` arms the card
 * instead of running; anything else clears the last message and runs.
 */
export async function pressAct($: EngineInterface, settings: Settings, act: Act): Promise<void> {
  const kind = act.command.kind
  if ((await getPending($)) !== null) {
    if (kind === 'no') await setPending($, null)
    if (kind !== 'yes') return
    const taken = await takePending($)
    const command = taken === null ? null : decodeConfirm(taken)
    if (command !== null) await perform($, settings, command)
    return
  }
  if (kind === 'yes' || kind === 'no') return
  if (act.confirm === true) {
    await askConfirm($, act.command)
    return
  }
  await clearMessage($)
  await perform($, settings, act.command)
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
