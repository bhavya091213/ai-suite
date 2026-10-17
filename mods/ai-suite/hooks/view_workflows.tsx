// Workflows: the phased workflow skills installed on this machine, with a SKILL.md preview.
import type { AiSuiteWorkflow } from '../types'
import { CARDS_PER_PAGE, pageOf, plural } from './summary'
import { actButton, buttonRow, card, empty, fit, heading, linesOf, line, note, pager } from './ui'
import type { Badge, Env } from './ui'

const PREVIEW_LINES = 12

const VALID: Badge = { text: '✓ valid', tone: 'success' }
const INVALID: Badge = { text: '! invalid', tone: 'error' }

function previewCard(env: Env, name: string, text: string): JSX.Element {
  const { Text } = env.els
  const all = linesOf(env, text)
  const paged = pageOf(all, env.data.pages.preview ?? 0, PREVIEW_LINES)
  return card(
    env,
    `preview-card:${name}`,
    null,
    heading(env, 'SKILL.md', name),
    ...paged.items.map(each => <Text wrap="truncate">{each === '' ? ' ' : each}</Text>),
    pager(env, 'preview', paged, all.length, PREVIEW_LINES),
    buttonRow(env, actButton(env, { key: 'close-preview', command: { kind: 'close-detail' } }, 'Close preview')),
  )
}

function workflowCard(env: Env, flow: AiSuiteWorkflow): JSX.Element {
  const { Box, Text } = env.els
  const isPreviewing = env.data.detail?.kind === 'preview' && env.data.detail.id === flow.name
  const status = flow.valid ? VALID : INVALID
  const counts = `${plural(flow.phases, 'phase', 'phases')} · ${plural(flow.skills, 'skill', 'skills')}`
  return card(
    env,
    `workflow:${flow.name}`,
    null,
    <Box flexDirection="row" gap={1}>
      <Text bold wrap="truncate">{fit(env, flow.name, status.text.length + 1)}</Text>
      <Text color={flow.valid ? 'success' : 'error'}>{status.text}</Text>
    </Box>,
    line(env, flow.valid || flow.note === '' ? counts : `${counts} · ${flow.note}`, flow.valid ? 'dim' : 'warning'),
    buttonRow(
      env,
      actButton(env, { key: `preview:${flow.name}`, command: { kind: 'preview', name: flow.name } }, isPreviewing ? 'Hide preview' : 'Preview SKILL.md'),
      actButton(env, { key: `workflow-retire:${flow.name}`, command: { kind: 'workflow-retire', name: flow.name }, confirm: true }, 'Retire…'),
      actButton(env, { key: `workflow-push:${flow.name}`, command: { kind: 'workflow-push', name: flow.name }, confirm: true }, 'Push to repo…'),
    ),
  )
}

export function workflows(env: Env): JSX.Element {
  const { Box, Text } = env.els
  const { workflows: snap } = env.data.snapshots
  const flows = snap.data ?? []
  const paged = pageOf(flows, env.data.pages.workflows ?? 0, CARDS_PER_PAGE)
  const detail = env.data.detail
  return (
    <Box flexDirection="column">
      {note(env, snap, 'workflows')}
      {snap.data !== null && flows.length === 0 &&
        empty(env, 'No workflows are installed yet.', actButton(env, { key: 'refresh', command: { kind: 'refresh' } }, 'Refresh'))}
      {paged.items.flatMap(flow => [
        workflowCard(env, flow),
        detail?.kind === 'preview' && detail.id === flow.name ? previewCard(env, flow.name, detail.text) : null,
      ])}
      {pager(env, 'workflows', paged, flows.length, CARDS_PER_PAGE)}
      <Text dimColor wrap="truncate">{fit(env, 'Create or edit workflows with ./install.sh (tab 0)')}</Text>
      {flows.length > 0 && <Box marginTop={1}>{actButton(env, { key: 'refresh', command: { kind: 'refresh' } }, 'Refresh')}</Box>}
    </Box>
  )
}
