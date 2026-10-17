// Updates: the git state of the repo, the commits you are behind, and the skills that changed upstream.
import type { AiSuiteGit, AiSuiteUpdates } from '../types'
import { CARDS_PER_PAGE, pageOf, plural, updatable } from './summary'
import { STATE_BADGES, actButton, actionRow, buttonRow, card, column, entry, fit, heading, line, skillCard } from './ui'
import type { Env } from './ui'
import { empty, note, pager } from './ui_parts'

const COMMITS_SHOWN = 5

function gitCard(env: Env, git: AiSuiteGit): JSX.Element {
  const detail =
    git.branch === ''
      ? ''
      : `branch ${git.branch} · upstream ${git.upstream || '(none)'} · ahead ${git.ahead} · behind ${git.behind} · last fetch ${git.lastFetch || 'never'}`
  const pull = git.behind > 0 ? `Pull ${plural(git.behind, 'commit', 'commits')}…` : 'Pull…'
  return card(
    env,
    'git',
    null,
    heading(env, 'Repository'),
    entry(
      env,
      line(env, git.message === '' ? 'No git information.' : git.message),
      detail !== '' && line(env, detail, 'dim'),
      git.hint !== '' && line(env, git.hint, 'warning'),
    ),
    buttonRow(
      env,
      actButton(env, { key: 'fetch', command: { kind: 'fetch' } }, 'Fetch'),
      git.upstream !== '' && actButton(env, { key: 'pull', command: { kind: 'pull' }, confirm: true }, pull),
    ),
  )
}

function commitsCard(env: Env, commits: readonly string[]): JSX.Element {
  const { Box, Text } = env.els
  return card(
    env,
    'commits',
    null,
    heading(env, 'Commits behind', String(commits.length)),
    entry(
      env,
      ...commits.slice(0, COMMITS_SHOWN).map(commit => {
        const cut = commit.indexOf(' ')
        const sha = cut < 0 ? commit : commit.slice(0, cut)
        return (
          <Box flexDirection="row" gap={1}>
            <Text dimColor>{sha}</Text>
            <Text wrap="truncate">{fit(env, cut < 0 ? '' : commit.slice(cut + 1), sha.length + 1)}</Text>
          </Box>
        )
      }),
      commits.length > COMMITS_SHOWN && <Text dimColor>{`… ${commits.length - COMMITS_SHOWN} more`}</Text>,
    ),
  )
}

function changedCards(env: Env, found: AiSuiteUpdates): JSX.Element {
  const { Box } = env.els
  const rows = env.data.snapshots.status.data ?? []
  const paged = pageOf(found.changed, env.data.pages.updates ?? 0, CARDS_PER_PAGE)
  const targets = updatable(rows, found)
  return (
    <Box {...column(env)}>
      {heading(env, 'Skills with upstream changes', String(found.changed.length))}
      {paged.items.map(change => {
        const id = `${change.scope}/${change.name}`
        const row = rows.find(each => each.scope === change.scope && each.name === change.name)
        const badge = STATE_BADGES[row?.state ?? ''] ?? { glyph: '·', word: 'not on this machine', tone: 'dim' as const }
        return skillCard(env, {
          scope: change.scope,
          name: change.name,
          badges: [badge],
          summary: { text: `${plural(change.files, 'file', 'files')} changed upstream`, tone: 'dim' },
          buttons: [
            row?.state === 'modified' &&
              actButton(env, { key: `update:${id}`, command: { kind: 'update', row: change } }, fit(env, `Update ${change.name}`, 24), { lead: true }),
          ],
        })
      })}
      {pager(env, 'updates', paged, found.changed.length, CARDS_PER_PAGE)}
      {targets.length > 0 &&
        actionRow(
          env,
          actButton(
            env,
            { key: 'update-changed', command: { kind: 'update-changed' }, confirm: true },
            `Update ${plural(targets.length, 'changed skill', 'changed skills')}…`,
            { primary: true },
          ),
        )}
    </Box>
  )
}

export function updates(env: Env): JSX.Element {
  const { Box } = env.els
  const { updates: snap } = env.data.snapshots
  const found = snap.data
  const isQuiet = found !== null && found.commits.length === 0 && found.changed.length === 0
  return (
    <Box {...column(env)}>
      {note(env, snap, 'updates')}
      {found !== null && gitCard(env, found.git)}
      {isQuiet && empty(env, 'Nothing has changed upstream.', actButton(env, { key: 'refresh', command: { kind: 'refresh' } }, 'Refresh'))}
      {found !== null && found.commits.length > 0 && commitsCard(env, found.commits)}
      {found !== null && found.changed.length > 0 && changedCards(env, found)}
      {found !== null && !isQuiet && <Box>{actButton(env, { key: 'refresh', command: { kind: 'refresh' } }, 'Refresh')}</Box>}
    </Box>
  )
}
