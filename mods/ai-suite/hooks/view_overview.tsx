// Overview: one card per scope with a bar, what needs attention, and the primary actions.
import type { Act } from './commands'
import { actButton, actionRow, card, column, entry, heading, line } from './ui'
import type { Env, Tone } from './ui'
import { counts, empty, listRow, note, progress } from './ui_parts'
import { countByScope, missingRows, plural, skillCounts } from './summary'
import type { ScopeCount } from './summary'

const SCOPES: readonly { id: string; title: string }[] = [
  { id: 'shared', title: 'Shared' },
  { id: 'claude', title: 'Claude' },
  { id: 'codex', title: 'Codex' },
]

function scopeCard(env: Env, scope: { id: string; title: string }, count: ScopeCount | undefined): JSX.Element {
  if (count === undefined) {
    return card(env, `scope:${scope.id}`, null, heading(env, scope.title), line(env, 'Nothing is offered in this scope.', 'dim'))
  }
  const offered = count.installed + count.modified + count.missing
  const present = count.installed + count.modified
  return card(
    env,
    `scope:${scope.id}`,
    null,
    heading(env, scope.title, `${present}/${offered}`),
    progress(env, count),
    counts(env, count),
  )
}

type Item = { text: string; tone: Tone; act: Act; label: string }

function attentionItems(env: Env): Item[] {
  const { status, updates, configFile, doctor } = env.data.snapshots
  const rows = status.data ?? []
  const counts = skillCounts(rows, updates)
  const modified = rows.filter(row => row.state === 'modified').length
  const behind = updates.data?.git.behind ?? 0
  const items: Item[] = []
  if (counts.problems > 0) {
    items.push({
      text: `${plural(counts.problems, 'skill has', 'skills have')} problems to repair`,
      tone: 'error',
      label: 'Show problems',
      act: { key: 'attention-problems', command: { kind: 'view', view: 'installed', installed: 'problems' } },
    })
  }
  if (configFile.data !== null && !configFile.data.exists) {
    items.push({
      text: 'No config.json yet: settings use the defaults',
      tone: 'warning',
      label: 'Open Settings',
      act: { key: 'attention-config', command: { kind: 'view', view: 'settings' } },
    })
  }
  if (behind > 0 || counts.changed > 0) {
    const parts = [
      behind > 0 ? plural(behind, 'commit', 'commits') + ' behind' : '',
      counts.changed > 0 ? plural(counts.changed, 'skill', 'skills') + ' changed upstream' : '',
    ].filter(part => part !== '')
    items.push({
      text: parts.join(' · '),
      tone: 'warning',
      label: 'Open Updates',
      act: { key: 'attention-updates', command: { kind: 'view', view: 'updates' } },
    })
  }
  if (modified > 0) {
    items.push({
      text: `${plural(modified, 'skill is', 'skills are')} modified locally`,
      tone: 'plain',
      label: 'Show modified',
      act: { key: 'attention-modified', command: { kind: 'view', view: 'installed', installed: 'modified' } },
    })
  }
  const missing = missingRows(rows).length
  if (missing > 0) {
    items.push({
      text: `${plural(missing, 'skill is', 'skills are')} not installed yet`,
      tone: 'plain',
      label: 'Review missing',
      act: { key: 'attention-missing', command: { kind: 'view', view: 'install' } },
    })
  }
  if ((doctor.data?.blockers ?? 0) > 0) {
    items.push({
      text: `Doctor found ${plural(doctor.data?.blockers ?? 0, 'blocker', 'blockers')}`,
      tone: 'error',
      label: 'Open Doctor',
      act: { key: 'attention-doctor', command: { kind: 'view', view: 'doctor' } },
    })
  }
  return items.slice(0, 5)
}

function attentionCard(env: Env): JSX.Element {
  const items = attentionItems(env)
  return card(
    env,
    'attention',
    null,
    heading(env, 'Needs attention', items.length === 0 ? '' : String(items.length)),
    items.length === 0
      ? line(env, '✓ Nothing needs attention.', 'success')
      : entry(env, ...items.map(item => listRow(env, item.tone, item.text, item.act, item.label))),
  )
}

export function overview(env: Env): JSX.Element {
  const { Box } = env.els
  const { status, configFile } = env.data.snapshots
  const rows = status.data
  const found = rows === null ? [] : countByScope(rows)
  const missing = rows === null ? 0 : missingRows(rows).length
  return (
    <Box {...column(env)}>
      {note(env, status, 'status')}
      {rows !== null && SCOPES.map(scope => scopeCard(env, scope, found.find(count => count.scope === scope.id)))}
      {rows !== null && attentionCard(env)}
      {rows === null && status.error === null && empty(env, 'Reading the skills…')}
      {actionRow(
        env,
        missing > 0 &&
          actButton(
            env,
            {
              key: 'overview-install',
              command: { kind: 'install-all', scope: 'all', query: '' },
              confirm: true,
            },
            `Install ${missing} missing`,
            { primary: true },
          ),
        actButton(env, { key: 'overview-fetch', command: { kind: 'fetch' } }, 'Check for updates'),
        configFile.data !== null &&
          !configFile.data.exists &&
          actButton(env, { key: 'overview-setup', command: { kind: 'view', view: 'settings' } }, 'Set up this machine'),
        actButton(env, { key: 'refresh', command: { kind: 'refresh' } }, 'Refresh'),
      )}
    </Box>
  )
}
