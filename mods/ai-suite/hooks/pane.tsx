// The Skills pane: the header, then the confirm card or the error callout if there is one, then
// one of seven views. The drawing is a pure function of PaneData; a control's press is handed to
// `dispatch`, which the hook binds to its own `$`. The same tree is drawn on every surface.
import type { AiSuiteView } from '../types'
import type { PaneData } from './state'
import { callout, confirmCard, fit, header, makeEnv } from './ui'
import type { Dispatch, Els, Env, PaneEls } from './ui'
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

/** The last result: a green or dim line for a success, the red callout for a failure. */
function feedback(env: Env): JSX.Element | null {
  const { message, repo } = env.data
  const { Box, Text } = env.els
  const repoError = repo !== null && repo.error !== '' && message?.text !== repo.error ? repo.error : ''
  if (message === null && repoError === '') return null
  return (
    <Box key="feedback" flexDirection="column">
      {message?.kind === 'error' && callout(env, 'Something went wrong', message.text)}
      {repoError !== '' && callout(env, 'Could not find the repo', repoError)}
      {message !== null && message.kind !== 'error' && (
        <Box marginBottom={1}>
          <Text {...(message.kind === 'ok' ? { color: 'success' } : { dimColor: true })} wrap="truncate">
            {fit(env, message.text)}
          </Text>
        </Box>
      )}
    </Box>
  )
}

export function renderPane(els: PaneEls, data: PaneData, bodyColumns: number, dispatch: Dispatch): JSX.Element {
  const { Box } = els
  const env = makeEnv(els, data, bodyColumns, dispatch)
  return (
    <Box flexDirection="column">
      {header(env)}
      {confirmCard(env)}
      {feedback(env)}
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
