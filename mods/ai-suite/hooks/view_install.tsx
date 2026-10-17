// Install: filter chips and a name filter over the skills the repo offers that are not installed yet.
import type { AiSuiteScopeFilter } from '../types'
import { CARDS_PER_PAGE, filterMissing, missingRows, pageOf } from './summary'
import { STATE_BADGES, actButton, buttonRow, card, chips, empty, fit, heading, note, pager, skillCard } from './ui'
import type { Env } from './ui'

const SCOPE_CHIPS: readonly { value: AiSuiteScopeFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'shared', label: 'Shared' },
  { value: 'claude', label: 'Claude' },
  { value: 'codex', label: 'Codex' },
]

const refresh = (env: Env): JSX.Element =>
  actButton(env, { key: 'refresh', command: { kind: 'refresh' } }, 'Refresh')

export function install(env: Env): JSX.Element {
  const { Box, Input } = env.els
  const { status } = env.data.snapshots
  const { installScope, installQuery } = env.data.filters
  const rows = status.data ?? []
  const missing = missingRows(rows)
  const shown = filterMissing(rows, env.data.filters)
  const paged = pageOf(shown, env.data.pages.install ?? 0, CARDS_PER_PAGE)
  const search = (text: string): Promise<void> =>
    env.dispatch({ key: 'install-query', command: { kind: 'query', text } })
  return (
    <Box flexDirection="column">
      {note(env, status, 'skills')}
      {status.data !== null && (
        <Box flexDirection="column">
          {chips(
            env,
            SCOPE_CHIPS.map(chip => ({
              key: chip.value,
              label: chip.label,
              isActive: chip.value === installScope,
              act: { key: `install-scope:${chip.value}`, command: { kind: 'scope', value: chip.value } },
            })),
          )}
          <Box marginBottom={1}>
            <Input
              key="install-query"
              label="Filter"
              placeholder="Filter by name…"
              value={installQuery}
              submitLabel="filter"
              onInput={search}
              onSubmit={search}
            />
          </Box>
        </Box>
      )}
      {status.data !== null && missing.length === 0 &&
        empty(env, 'Everything is installed.', actButton(env, { key: 'install-check', command: { kind: 'fetch' } }, 'Check updates'))}
      {missing.length > 0 && shown.length === 0 &&
        empty(env, 'No missing skill matches this filter.', actButton(env, { key: 'install-show-all', command: { kind: 'scope', value: 'all' } }, 'Show all'))}
      {paged.items.map(row =>
        skillCard(env, {
          scope: row.scope,
          name: row.name,
          badges: [STATE_BADGES['not-installed'] ?? { text: '· missing', tone: 'dim' }],
          summary: { text: row.description === '' ? '(no description)' : row.description, tone: 'dim' },
          buttons: [
            actButton(
              env,
              { key: `install:${row.scope}/${row.name}`, command: { kind: 'install', row } },
              fit(env, `Install ${row.name}`, 24),
            ),
          ],
        }),
      )}
      {pager(env, 'install', paged, shown.length, CARDS_PER_PAGE)}
      {shown.length > 0 &&
        card(
          env,
          'install-footer',
          null,
          heading(env, 'Install everything shown', String(shown.length)),
          buttonRow(
            env,
            actButton(
              env,
              {
                key: 'install-all',
                command: { kind: 'install-all', scope: installScope, query: installQuery },
                confirm: true,
              },
              `Install all ${shown.length}`,
              { primary: true },
            ),
            refresh(env),
          ),
        )}
      {shown.length === 0 && <Box>{refresh(env)}</Box>}
    </Box>
  )
}
