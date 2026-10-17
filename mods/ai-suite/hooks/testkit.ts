// Shared by the *.test.ts files (not a test itself): canned installer output, and a
// `world` that answers everything beneath the plugin and records what it was asked.
import type { On, RenderPropsOf } from 'claude-code'
import { mock } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'

export const REPO = '/work/ai-suite'
export const SURFACES = ['terminal', 'desktop'] as const
export const PY = ['python3', '-m', 'installer', '--repo', REPO]
export const AT_REPO = { options: { repoPath: REPO } }

// ------------------------------------------------------------------ fixtures

const skill = (scope: string, name: string, state: string, extra: object = {}) => ({
  scope,
  name,
  state,
  source: state === 'foreign' ? null : { meta: { description: `${name} skill` } },
  installed: state === 'not-installed' ? null : { kind: 'dir' },
  links: [],
  duplicates: [],
  issues: [],
  remote: null,
  ...extra,
})

const STATUS = [
  skill('shared', 'alpha', 'installed'),
  skill('shared', 'beta', 'modified', {
    issues: ['claude: real directory shadows the shared skill'],
    links: [{ consumer: 'claude', state: 'real-dir' }],
  }),
  skill('shared', 'dup', 'not-installed'),
  skill('claude', 'gamma', 'installed'),
  skill('claude', 'ghost', 'foreign', { issues: ['broken symlink'] }),
]
const CATALOG = [
  { scope: 'shared', name: 'alpha', state: 'installed', installed: 'yes', description: 'Alpha skill' },
  { scope: 'shared', name: 'dup', state: 'not-installed', installed: 'no', description: 'Duplicated skill' },
  { scope: 'claude', name: 'nometa', state: 'not-installed', installed: 'no', description: '' },
]
const ISSUES = {
  problems: [
    {
      ...skill('shared', 'beta', 'modified'),
      issues: ['claude: real directory shadows the shared skill'],
      links: [{ consumer: 'claude', state: 'real-dir' }, { consumer: 'codex', state: 'ok' }],
    },
    { ...skill('claude', 'ghost', 'foreign'), issues: ['broken symlink -> nowhere'] },
  ],
  repo_issues: [],
}
const UPDATES = {
  git: {
    message: '3 commits behind origin/main',
    hint: '',
    branch: 'main',
    upstream: 'origin/main',
    ahead: 0,
    behind: 3,
    last_fetch: 1760000000,
  },
  commits: ['abc1234 feat: one', 'def5678 fix: two', '0123456 docs: three'],
  changed: [{ scope: 'shared', name: 'beta', files: ['SKILL.md'] }],
}
const DOCTOR = {
  checks: [
    { name: 'python', state: 'ok', text: '3.14.7' },
    { name: 'git', state: 'warn', text: 'not a checkout' },
  ],
  blockers: 0,
}
const WORKFLOWS = [
  { name: 'ship', workflow: 'ship', path: '/x', phases: 3, skills: 5, valid: true, errors: [], warnings: [] },
]

export type Answer = { exitCode: number; stdout: string; stderr: string }
export const json = (value: unknown): Answer => ({ exitCode: 0, stdout: JSON.stringify(value), stderr: '' })
export const text = (stdout: string): Answer => ({ exitCode: 0, stdout, stderr: '' })
export const bad = (stderr: string, exitCode = 2): Answer => ({ exitCode, stdout: '', stderr })

const CANNED: Record<string, Answer> = {
  'status --json': json(STATUS),
  'list --json': json(CATALOG),
  'issues --json': json(ISSUES),
  'updates --json': json(UPDATES),
  'updates --json --fetch': json(UPDATES),
  'workflow list --json': json(WORKFLOWS),
  'doctor --json': json(DOCTOR),
}

// --------------------------------------------------------------------- world

export type WorldOptions = {
  canned?: Record<string, Answer>
  hasRepo?: boolean
  refuse?: string[]
}

const MUTATING = /^(install|update|retire|relink|pull|apply)\b/
const DONE = text('Plan (1 step(s)):\n  1. mkdir x\n  ok    mkdir x\nDone.\n')

/** Answers every call on `$` beneath the plugin and records what it was asked. */
export function world(on: On, options: WorldOptions = {}) {
  const answers = { ...CANNED, ...options.canned }
  const hasRepo = options.hasRepo !== false
  const calls: { argv: string[]; cwd: string | undefined }[] = []
  const toasts: string[] = []
  const statuses: (string | undefined)[] = []
  const registered: string[] = []
  const opened: string[] = []
  const probed: string[] = []
  const clock = mock.clock(on)
  mock.env(on, { HOME: '/sandbox/user' })
  on('process.run', (_$, e) => {
    calls.push({ argv: [...e.argv], cwd: e.init?.cwd })
    const key = e.argv.slice(5).join(' ')
    const answer = answers[key] ?? (MUTATING.test(key) ? DONE : bad(`no canned answer for ${key}`))
    return { value: { ...answer, isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('fs.exists', (_$, e) => {
    probed.push(e.path)
    return { value: hasRepo }
  })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('command.register', (_$, e) => {
    if (options.refuse?.includes(e.name)) return { deny: 'a name Claude Code ships' }
    registered.push(e.name)
    return { value: { command: e.name } }
  })
  on('ui.open', (_$, e) => {
    opened.push(e.id)
    return { value: { isPlaced: true as const } }
  })
  on('ui.toast', (_$, e) => {
    toasts.push(e.text)
    return { value: undefined }
  })
  on('ui.status', (_$, e) => {
    statuses.push(e.text)
    return { value: undefined }
  })
  on('ui.log', () => ({ value: undefined }))
  /** Each call as `status --json`: what follows `python3 -m installer --repo <repo>`. */
  const commands = () => calls.map(call => call.argv.slice(5).join(' '))
  return { calls, toasts, statuses, registered, opened, probed, clock, commands }
}

/** Lets work the plugin left running unawaited (the start check) run to its end. */
export async function flush(clock: { settle: () => Promise<void> }): Promise<void> {
  for (let at = 0; at < 8; at += 1) await clock.settle()
}

// ------------------------------------------------------------------- the pane

export const PANE: RenderPropsOf['Pane'] = {
  title: 'Skills',
  isFocused: true,
  bodyColumns: 100,
  placement: 'dock',
  scroll: { offset: 0, bodyRows: 40 },
  view: {},
}

/** The input of a typed slash command, as the engine raises command.run. */
export const run = (name: string) => ({
  command: name,
  args: '',
  origin: { kind: 'composer' as const },
  presentation: { isFullscreen: true, columns: 100 },
})

export function mountPane($: Engine, surface: (typeof SURFACES)[number], props = PANE, rows = 40) {
  return $.ui.mount({
    plugin: 'ai-suite',
    surface,
    component: 'Pane',
    props,
    requestId: 'ai-suite',
    viewport: { columns: 100, rows },
  })
}

type Query = { key?: string; type?: string; text?: string | RegExp }
type Drawn = {
  find: (query: Query) => Promise<{ props: Record<string, unknown> } | undefined>
  findAll: (query: Query) => Promise<unknown[]>
}

export async function labelOf(ui: Drawn, key: string): Promise<unknown> {
  return (await ui.find({ key }))?.props.label
}

export async function textCount(ui: Drawn, pattern: RegExp): Promise<number> {
  return (await ui.findAll({ type: 'Text', text: pattern })).length
}
