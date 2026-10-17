// The Skills pane: the header (with the last action's one dim line under the status strip), then
// the error callout if there is one, then one of seven views, which draw a pending confirm card
// right where the press that asked for it was. The drawing is a pure function of PaneData; a
// control's press is handed to `dispatch`, which the hook binds to its own `$`. The terminal gets a tight grid with hotkeys; the
// desktop app and the editor get a padded page, a tab row without key caps and an Svg bar.
import type { BoxProps } from 'claude-code'
import type { AiSuiteView } from '../types'
import { trimMessage, truncate } from './cli'
import { TOP } from './commands'
import { VIEWS } from './state'
import type { PaneData } from './state'
import { plural, skillCounts } from './summary'
import { actButton, apart, hue, makeEnv, toneProps } from './ui'
import type { Dispatch, Els, Env, Look, PaneEls, Tone } from './ui'
import { callout, confirmAfter } from './ui_parts'
import { doctor } from './view_doctor'
import { install } from './view_install'
import { installed } from './view_installed'
import { overview } from './view_overview'
import { settings } from './view_settings'
import { updates } from './view_updates'
import { workflows } from './view_workflows'

const BODIES: Record<AiSuiteView, (env: Env) => JSX.Element> = {
  overview,
  install,
  installed,
  updates,
  settings,
  workflows,
  doctor,
}

// -------------------------------------------------------------------- header

type Segment = { text: string; tone: Tone }

function strip(data: PaneData): Segment[] {
  const { status, updates: found } = data.snapshots
  const out: Segment[] = []
  if (status.data !== null) {
    const counts = skillCounts(status.data, found)
    out.push({ text: `${counts.present}/${counts.offered} installed`, tone: counts.present === counts.offered ? 'success' : 'plain' })
    if (counts.changed > 0) out.push({ text: plural(counts.changed, 'update', 'updates'), tone: 'warning' })
    if (counts.problems > 0) out.push({ text: plural(counts.problems, 'issue', 'issues'), tone: 'error' })
  } else {
    out.push({ text: status.error === null ? 'Loading…' : 'status unavailable', tone: status.error === null ? 'dim' : 'error' })
  }
  if (data.busy !== null) out.push({ text: `Working… ${data.busy.label}`, tone: 'warning' })
  return out
}

function repoLine(data: PaneData): Segment {
  const { repo } = data
  if (repo !== null && repo.error !== '') return { text: 'repo not found', tone: 'error' }
  const git = data.snapshots.updates.data?.git
  const parts = [
    repo?.shown ?? '',
    git?.branch ?? '',
    git === undefined ? '' : git.behind > 0 ? `${git.behind} behind` : '',
  ].filter(part => part !== '')
  return { text: parts.join(' · '), tone: 'dim' }
}

/** The tab row: plain buttons, the open view bold and underlined (in Claude's colour on the desktop, where the rest are dim and no hotkey is drawn). */
function tabs(env: Env): JSX.Element {
  const { Box } = env.els
  return (
    <Box flexDirection="row" flexWrap="wrap" gap={env.isDesktop ? 2 : 1}>
      {VIEWS.map(entry =>
        actButton(env, { key: `view-${entry.id}`, command: { kind: 'view', view: entry.id } }, entry.label, {
          plain: true,
          hotkey: entry.hotkey,
          isActive: entry.id === env.data.view,
        }),
      )}
    </Box>
  )
}

/** The status strip: segments separated by `·` in the terminal, a coloured `●` before each dim label on the desktop. */
function statusStrip(env: Env): JSX.Element {
  const { Box, Text } = env.els
  const segments = strip(env.data)
  if (!env.isDesktop) {
    return (
      <Box flexDirection="row" gap={1}>
        {segments.flatMap((segment, at) => [
          at > 0 ? <Text key={`dot-${at}`} dimColor>·</Text> : null,
          <Text key={`segment-${at}`} {...toneProps(segment.tone)} wrap="truncate">{segment.text}</Text>,
        ])}
      </Box>
    )
  }
  return (
    <Box flexDirection="row" flexWrap="wrap" gap={2}>
      {segments.map(segment => (
        <Box flexDirection="row" gap={1}>
          <Text color={hue(segment.tone === 'plain' ? 'dim' : segment.tone)}>●</Text>
          <Text dimColor wrap="truncate">{segment.text}</Text>
        </Box>
      ))}
    </Box>
  )
}

/** Cells the desktop page's own padding takes from the pane's width (two on each side). */
const ROOT_PADDING = 4

/** The last result that is not a failure: one dim line, the whole sentence unless the pane is too narrow for it. */
function lastAction(env: Env): JSX.Element | null {
  const { message } = env.data
  if (message === null || message.kind === 'error') return null
  const { Text } = env.els
  const room = Math.max(8, env.columns - (env.isDesktop ? ROOT_PADDING : 0))
  return <Text key="last-action" dimColor wrap="truncate">{trimMessage(message.text, room)}</Text>
}

/** Title and repo line, the tab row (terminal hotkeys `o i s u t w d`), the status strip and the last action's line. */
export function header(env: Env): JSX.Element {
  const { Box, Text } = env.els
  const title = env.isDesktop ? 'Skills' : 'AI Suite · Skills'
  const right = repoLine(env.data)
  const look: BoxProps = env.isDesktop ? { gap: 1 } : { marginBottom: 1 }
  return (
    <Box key="header" flexDirection="column" {...look}>
      <Box flexDirection="row" justifyContent="space-between" gap={2}>
        <Text bold>{title}</Text>
        <Text {...toneProps(right.tone)} wrap="truncate">{truncate(right.text, Math.max(8, env.columns - title.length - 2))}</Text>
      </Box>
      {tabs(env)}
      <Box key="strip" flexDirection="column">
        {statusStrip(env)}
        {lastAction(env)}
      </Box>
    </Box>
  )
}

// ---------------------------------------------------------------------- body

/** A failure, or a repo that cannot be found: the red callouts, below the header and before the filters. */
function errors(env: Env): JSX.Element | null {
  const { message, repo } = env.data
  const failure = message?.kind === 'error' ? message.text : ''
  const repoError = repo !== null && repo.error !== '' && message?.text !== repo.error ? repo.error : ''
  if (failure === '' && repoError === '') return null
  const { Box } = env.els
  return (
    <Box key="errors" flexDirection="column" {...apart(env)}>
      {failure !== '' && callout(env, 'Something went wrong', failure)}
      {repoError !== '' && callout(env, 'Could not find the repo', repoError)}
    </Box>
  )
}

/** The pane's root: the desktop page is padded two cells in and spaces its children a blank row apart. */
const root = (env: Env): BoxProps =>
  env.isDesktop ? { paddingX: 2, paddingY: 1, gap: 1, width: '100%' } : {}

export function renderPane(
  els: PaneEls,
  data: PaneData,
  bodyColumns: number,
  dispatch: Dispatch,
  look?: Look,
): JSX.Element {
  const { Box } = els
  const env = makeEnv(els, data, bodyColumns, dispatch, look)
  return (
    <Box flexDirection="column" {...root(env)}>
      {header(env)}
      {errors(env)}
      {confirmAfter(env, TOP)}
      {BODIES[data.view](env)}
    </Box>
  )
}

/** A surface with no text fields or pickers (the mobile app) cannot draw the pane; it says so. */
export function renderUnsupported(els: Els): JSX.Element {
  const { Box, Text } = els
  return (
    <Box flexDirection="column">
      <Text bold>AI Suite · Skills</Text>
      <Text dimColor>The Skills pane needs the terminal or the desktop app.</Text>
    </Box>
  )
}
