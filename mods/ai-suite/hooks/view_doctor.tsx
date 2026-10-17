// Doctor: the installer's checks as coloured rows, and the tools found on this machine.
import type { AiSuiteCaps, AiSuiteCheckState, AiSuiteDoctor } from '../types'
import { pageOf, plural } from './summary'
import { actButton, card, column, entry, fit, heading, hue, line, toneProps, viewRow } from './ui'
import type { Env, Tone } from './ui'
import { empty, note, pager } from './ui_parts'

const CHECKS_PER_PAGE = 8
const NAME_WIDTH = 16

const GLYPHS: Record<AiSuiteCheckState, { glyph: string; tone: Tone }> = {
  ok: { glyph: '✓', tone: 'success' },
  warn: { glyph: '!', tone: 'warning' },
  blocker: { glyph: '✗', tone: 'error' },
}

function checksCard(env: Env, found: AiSuiteDoctor): JSX.Element {
  const { Box, Text } = env.els
  const warns = found.checks.filter(check => check.state === 'warn').length
  const paged = pageOf(found.checks, env.data.pages.doctor ?? 0, CHECKS_PER_PAGE)
  const summary = `${found.blockers === 0 ? 'no blockers' : plural(found.blockers, 'blocker', 'blockers')} · ${plural(warns, 'warning', 'warnings')}`
  return card(
    env,
    'checks',
    null,
    heading(env, 'Checks'),
    line(env, summary, found.blockers > 0 ? 'error' : warns > 0 ? 'warning' : 'success'),
    entry(
      env,
      ...paged.items.map(check => {
        const mark = GLYPHS[check.state]
        return (
          <Box flexDirection="row" gap={env.isDesktop ? 2 : 1}>
            <Text {...(env.isDesktop ? { color: hue(mark.tone) } : toneProps(mark.tone))}>{mark.glyph}</Text>
            <Text bold wrap="truncate">{fit(env, check.name, 4)}</Text>
            <Text dimColor wrap="truncate">{fit(env, check.text, check.name.length + 4)}</Text>
          </Box>
        )
      }),
    ),
    pager(env, 'doctor', paged, found.checks.length, CHECKS_PER_PAGE, {}),
  )
}

function toolsCard(env: Env, caps: AiSuiteCaps): JSX.Element {
  const { Box, Text } = env.els
  return card(
    env,
    'tools',
    null,
    heading(env, 'Tools on this machine'),
    entry(
      env,
      ...caps.tools.map(tool => (
        <Box flexDirection="row" gap={env.isDesktop ? 2 : 1}>
          <Box width={NAME_WIDTH}>
            <Text wrap="truncate">{fit(env, tool.name, env.inner - NAME_WIDTH)}</Text>
          </Box>
          <Text {...toneProps(tool.present ? 'plain' : 'dim')} wrap="truncate">
            {fit(env, tool.present ? tool.version || 'found' : 'not found', NAME_WIDTH + 1)}
          </Text>
        </Box>
      )),
    ),
  )
}

export function doctor(env: Env): JSX.Element {
  const { Box } = env.els
  const { doctor: snap, caps } = env.data.snapshots
  return (
    <Box {...column(env)}>
      {note(env, snap, 'checks')}
      {snap.data !== null && snap.data.checks.length === 0 &&
        empty(env, 'The installer reported no checks.')}
      {snap.data !== null && snap.data.checks.length > 0 && checksCard(env, snap.data)}
      {caps.data === null && caps.error !== null && <Box>{note(env, caps, 'tools')}</Box>}
      {caps.data !== null && caps.data.tools.length > 0 && toolsCard(env, caps.data)}
      {snap.data !== null && viewRow(env, actButton(env, { key: 'refresh', command: { kind: 'refresh' } }, 'Run checks again'))}
    </Box>
  )
}
