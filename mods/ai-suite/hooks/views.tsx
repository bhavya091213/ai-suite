// The Skills pane: a view switcher, a message row and one of six views. The
// drawing is a pure function of PaneData; a button's press is handed to
// `dispatch`, which the hook binds to its own `$`. The same tree is drawn on
// every surface.
import type { Elements } from 'claude-code'
import type { AiSuiteSnapshot, AiSuiteView } from '../types'
import type { Act } from './actions'
import { truncate } from './cli'
import { VIEWS } from './state'
import type { PaneData } from './state'
import { countByScope, pageOf, plural, scopeLine } from './summary'
import type { Page } from './summary'

/** The three elements every surface has, which is all this pane draws with. */
export type Els = Pick<Elements['terminal'], 'Box' | 'Text' | 'Button'>
export type PaneSize = { rows: number; columns: number }
export type Dispatch = (act: Act) => Promise<void>

type Env = { els: Els; data: PaneData; room: number; columns: number; dispatch: Dispatch }

// Rows the switcher, message, view header and footer take out of the pane.
const CHROME_ROWS = 9

function button(env: Env, act: Act): JSX.Element {
  const { Button } = env.els
  const isArmed = act.confirm !== undefined && env.data.pending === act.key
  const extra = {
    ...(act.hotkey === undefined ? {} : { hotkey: act.hotkey }),
    ...(act.isPrimary === true ? { variant: 'primary' as const } : {}),
  }
  return (
    <Button
      key={act.key}
      label={isArmed ? `Confirm ${act.label.toLowerCase()}` : act.label}
      {...extra}
      onPress={() => env.dispatch(act)}
    />
  )
}

const refreshAct = (env: Env): Act => ({
  key: 'refresh',
  label: 'Refresh',
  hotkey: 'r',
  command: { kind: 'refresh', view: env.data.view },
})

function note(env: Env, snap: AiSuiteSnapshot<unknown>, what: string): JSX.Element | null {
  const { Text } = env.els
  if (snap.data === null && snap.error === null) {
    return <Text dimColor>{`${what} is not loaded yet. Press Refresh (r).`}</Text>
  }
  if (snap.data === null) return <Text color="error">{`${what}: ${snap.error ?? ''}`}</Text>
  if (snap.error !== null) {
    return <Text color="warning">{`(showing older ${what}; the last refresh failed: ${truncate(snap.error, 80)})`}</Text>
  }
  return null
}

function pager(env: Env, paged: Page<unknown>): JSX.Element | null {
  if (paged.pages <= 1) return null
  const { Box, Text } = env.els
  const more = paged.hidden > 0 ? ` · ${paged.hidden} more` : ''
  return (
    <Box key="pager" flexDirection="row" gap={1}>
      {paged.page > 0 &&
        button(env, { key: 'page-prev', label: 'Prev', hotkey: 'b', command: { kind: 'page', page: paged.page - 1 } })}
      {paged.page < paged.pages - 1 &&
        button(env, { key: 'page-next', label: 'Next', hotkey: 'n', command: { kind: 'page', page: paged.page + 1 } })}
      <Text dimColor>{`page ${paged.page + 1}/${paged.pages}${more}`}</Text>
    </Box>
  )
}

// --------------------------------------------------------------------- views

function overview(env: Env): JSX.Element {
  const { Box, Text } = env.els
  const { repo } = env.data
  const { status, updates } = env.data.snapshots
  const git = updates.data?.git
  const gitLine = git === undefined
    ? 'git: not checked yet'
    : `git: ${git.message}${git.hint === '' ? '' : ` · ${git.hint}`}`
  const repoError = repo !== null && repo.error !== ''
  const repoLine = repo === null ? 'Repo: (not resolved yet)' : repoError ? repo.error : `Repo: ${repo.shown}`
  return (
    <Box key="overview" flexDirection="column">
      <Text bold {...(repoError ? { color: 'error' } : {})}>{repoLine}</Text>
      <Text wrap="truncate">{gitLine}</Text>
      {note(env, status, 'status')}
      {(status.data === null ? [] : countByScope(status.data)).map(count => (
        <Box key={`scope-${count.scope}`}>
          <Text>{scopeLine(count)}</Text>
        </Box>
      ))}
      <Box key="actions" flexDirection="row" gap={1}>
        {button(env, refreshAct(env))}
        {button(env, {
          key: 'apply',
          label: 'Apply config',
          hotkey: 'a',
          confirm: 'Apply runs install.sh --headless --auto and syncs settings.',
          command: { kind: 'apply' },
        })}
      </Box>
    </Box>
  )
}

function install(env: Env): JSX.Element {
  const { Box, Text } = env.els
  const { catalog } = env.data.snapshots
  const missing = (catalog.data ?? []).filter(row => row.state === 'not-installed')
  const paged = pageOf(missing, env.data.page, env.room)
  return (
    <Box key="install" flexDirection="column">
      {note(env, catalog, 'skill list')}
      {catalog.data !== null && (
        <Text bold>{missing.length === 0 ? 'Everything in the repo is installed.' : `${missing.length} not installed`}</Text>
      )}
      {paged.items.map(row => (
        <Box key={`row-${row.scope}/${row.name}`} flexDirection="row" gap={1}>
          {button(env, {
            key: `install:${row.scope}/${row.name}`,
            label: 'Install',
            command: { kind: 'install', row },
          })}
          <Text wrap="truncate">
            {`${row.scope}/${row.name}  ${truncate(row.description, Math.max(12, env.columns - row.name.length - 24))}`}
          </Text>
        </Box>
      ))}
      {pager(env, paged)}
      <Box key="actions" flexDirection="row" gap={1}>
        {button(env, refreshAct(env))}
        {missing.length > 0 &&
          button(env, {
            key: 'install-all',
            label: 'Install all missing',
            hotkey: 'a',
            confirm: `Install ${missing.length} skills?`,
            command: { kind: 'install-all' },
          })}
      </Box>
    </Box>
  )
}

function issues(env: Env): JSX.Element {
  const { Box, Text } = env.els
  const { issues: snap } = env.data.snapshots
  const found = snap.data
  const total = found === null ? 0 : found.problems.length + found.repoIssues.length
  const paged = pageOf(found?.problems ?? [], env.data.page, env.room)
  return (
    <Box key="issues" flexDirection="column">
      {note(env, snap, 'issues')}
      {found !== null && <Text bold>{total === 0 ? 'No problems found.' : plural(total, 'problem', 'problems')}</Text>}
      {paged.items.map(problem => {
        const id = `${problem.scope}/${problem.name}`
        return (
          <Box key={`row-${id}`} flexDirection="row" gap={1}>
            {problem.canRelink &&
              button(env, { key: `relink:${id}`, label: 'Relink', command: { kind: 'relink', row: problem } })}
            {problem.canRetire &&
              button(env, {
                key: `retire:${id}`,
                label: 'Retire',
                confirm: `Retire ${id}? It is moved to a backup.`,
                command: { kind: 'retire', row: problem },
              })}
            <Text wrap="truncate">{`${id} [${problem.state}] ${problem.text}`}</Text>
          </Box>
        )
      })}
      {paged.page === paged.pages - 1 &&
        (found?.repoIssues ?? []).slice(0, 3).map(item => (
          <Box key={`repo-${item.scope}/${item.name}`}>
            <Text wrap="truncate" dimColor>{`repo ${item.scope}/${item.name}: ${item.message}`}</Text>
          </Box>
        ))}
      {pager(env, paged)}
      <Box key="actions">{button(env, refreshAct(env))}</Box>
    </Box>
  )
}

function updates(env: Env): JSX.Element {
  const { Box, Text } = env.els
  const { updates: snap } = env.data.snapshots
  const found = snap.data
  const half = Math.max(2, Math.floor(env.room / 2))
  const commits = found?.commits ?? []
  const changed = found?.changed ?? []
  const git = found?.git
  return (
    <Box key="updates" flexDirection="column">
      {note(env, snap, 'updates')}
      {git !== undefined && (
        <Box key="git" flexDirection="column">
          <Text bold>{`${git.message}${git.hint === '' ? '' : ` · ${git.hint}`}`}</Text>
          {git.branch !== '' && (
            <Text wrap="truncate" dimColor>
              {`branch ${git.branch} · upstream ${git.upstream || '(none)'} · ahead ${git.ahead} · behind ${git.behind} · last fetch ${git.lastFetch || 'never'}`}
            </Text>
          )}
        </Box>
      )}
      {found !== null && <Text bold>{`Commits behind (${commits.length})`}</Text>}
      {commits.slice(0, half).map(line => (
        <Box key={`commit-${line}`}>
          <Text wrap="truncate">{`  ${line}`}</Text>
        </Box>
      ))}
      {commits.length > half && <Text dimColor>{`  ${commits.length - half} more`}</Text>}
      {found !== null && <Text bold>{`Skills with upstream changes (${changed.length})`}</Text>}
      {changed.slice(0, half).map(item => (
        <Box key={`changed-${item.scope}/${item.name}`}>
          <Text wrap="truncate">{`  ${item.scope}/${item.name} (${item.files} files)`}</Text>
        </Box>
      ))}
      {changed.length > half && <Text dimColor>{`  ${changed.length - half} more`}</Text>}
      <Box key="actions" flexDirection="row" gap={1}>
        {button(env, { key: 'fetch', label: 'Fetch', hotkey: 'f', command: { kind: 'fetch' } })}
        {button(env, {
          key: 'pull',
          label: 'Pull',
          hotkey: 'p',
          confirm: 'Pull runs git pull --ff-only in the repo.',
          command: { kind: 'pull' },
        })}
        {button(env, {
          key: 'update-changed',
          label: 'Update changed',
          hotkey: 'c',
          confirm: 'Update replaces every modified skill that has an upstream change with the repo copy (backed up).',
          command: { kind: 'update-changed' },
        })}
        {button(env, refreshAct(env))}
      </Box>
    </Box>
  )
}

function workflows(env: Env): JSX.Element {
  const { Box, Text } = env.els
  const { workflows: snap } = env.data.snapshots
  const paged = pageOf(snap.data ?? [], env.data.page, env.room)
  return (
    <Box key="workflows" flexDirection="column">
      {note(env, snap, 'workflows')}
      {snap.data !== null && snap.data.length === 0 && <Text>No workflows installed yet.</Text>}
      {paged.items.map(flow => (
        <Box key={`flow-${flow.name}`}>
          <Text wrap="truncate">
            {`${flow.name}  ${plural(flow.phases, 'phase', 'phases')} · ${plural(flow.skills, 'skill', 'skills')} · ${flow.valid ? 'valid' : `invalid${flow.note === '' ? '' : `: ${flow.note}`}`}`}
          </Text>
        </Box>
      ))}
      {pager(env, paged)}
      <Text dimColor>Create and edit workflows in ./install.sh (Workflows tab, key 0).</Text>
      <Box key="actions">{button(env, refreshAct(env))}</Box>
    </Box>
  )
}

function doctor(env: Env): JSX.Element {
  const { Box, Text } = env.els
  const { doctor: snap } = env.data.snapshots
  const checks = snap.data?.checks ?? []
  const warns = checks.filter(check => check.state === 'warn').length
  const paged = pageOf(checks, env.data.page, env.room)
  const colors = { ok: 'success', warn: 'warning', blocker: 'error' } as const
  return (
    <Box key="doctor" flexDirection="column">
      {note(env, snap, 'doctor')}
      {snap.data !== null && (
        <Text bold>{`${snap.data.blockers === 0 ? 'no blockers' : plural(snap.data.blockers, 'blocker', 'blockers')} · ${plural(warns, 'warning', 'warnings')}`}</Text>
      )}
      {paged.items.map((check, at) => (
        <Box key={`check-${paged.page}-${at}`}>
          <Text wrap="truncate" color={colors[check.state]}>
            {`[${check.state}] ${check.name}${check.name !== '' && check.text !== '' ? ': ' : ''}${check.text}`}
          </Text>
        </Box>
      ))}
      {pager(env, paged)}
      <Box key="actions">{button(env, refreshAct(env))}</Box>
    </Box>
  )
}

const BODIES: Record<AiSuiteView, (env: Env) => JSX.Element> = {
  overview,
  install,
  issues,
  updates,
  workflows,
  doctor,
}

// ---------------------------------------------------------------------- pane

export function renderPane(els: Els, data: PaneData, size: PaneSize, dispatch: Dispatch): JSX.Element {
  const { Box, Text } = els
  const env: Env = {
    els,
    data,
    dispatch,
    room: Math.max(3, size.rows - CHROME_ROWS),
    columns: size.columns,
  }
  const { busy, message } = data
  const color = message === null ? undefined : message.kind === 'error' ? 'error' : message.kind === 'ok' ? 'success' : undefined
  return (
    <Box flexDirection="column">
      <Box key="views" flexDirection="row" flexWrap="wrap" gap={1}>
        {VIEWS.map(entry =>
          button(env, {
            key: `view-${entry.id}`,
            label: entry.label,
            hotkey: entry.hotkey,
            isPrimary: entry.id === data.view,
            command: { kind: 'view', view: entry.id },
          }),
        )}
      </Box>
      <Box key="message" flexDirection="column">
        {busy !== null && <Text color="warning">{`Working: ${busy.label}...`}</Text>}
        {message !== null && (
          <Text wrap="wrap" {...(color === undefined ? {} : { color })}>{message.text}</Text>
        )}
      </Box>
      {BODIES[data.view](env)}
    </Box>
  )
}
