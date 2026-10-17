// Shared by the *.test.ts files (not a test itself): canned installer output, and a
// `world` that answers everything beneath the plugin and records what it was asked.
import type { On, RenderPropsOf } from 'claude-code'
import { mock } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'

export const REPO = '/work/ai-suite'
export const SURFACES = ['terminal', 'desktop'] as const
/** Every surface the pane draws on: the editor's webview is a desktop-style page without `Client`. */
export type Surface = (typeof SURFACES)[number] | 'vscode'
/** The desktop app and the editor share one look (padded page, Svg bar, tabs without hotkeys). */
export const isDesktop = (surface: Surface): boolean => surface !== 'terminal'
/** `text` as an anchored pattern, its punctuation taken literally. */
export const exact = (text: string): RegExp => new RegExp(`^${text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`)
/** A badge as the surface draws it: `✓ installed` in the terminal, `● installed` on the desktop. */
export const badgeText = (surface: Surface, terminal: string): string =>
  isDesktop(surface) ? terminal.replace(/^\S+/, '●') : terminal
export const PY = ['python3', '-m', 'installer', '--repo', REPO]
export const AT_REPO = { options: { repoPath: REPO } }

// ------------------------------------------------------------------ fixtures

export const skill = (scope: string, name: string, state: string, extra: object = {}) => ({
  scope,
  name,
  state,
  source: state === 'foreign' || state === 'ignored' ? null : { meta: { description: `${name} skill` } },
  installed: state === 'not-installed' ? null : { kind: 'dir' },
  links: [],
  duplicates: [],
  issues: [],
  remote: null,
  ...extra,
})

const OK_LINKS = [{ consumer: 'claude', state: 'ok' }, { consumer: 'codex', state: 'ok' }]

export const STATUS = [
  skill('shared', 'alpha', 'installed', { links: OK_LINKS }),
  skill('shared', 'beta', 'modified', {
    issues: ['claude: real directory shadows the shared skill'],
    links: [{ consumer: 'claude', state: 'real-dir' }, { consumer: 'codex', state: 'ok' }],
  }),
  skill('shared', 'dup', 'not-installed', {
    links: [{ consumer: 'claude', state: 'missing' }, { consumer: 'codex', state: 'missing' }],
  }),
  skill('claude', 'gamma', 'installed'),
  skill('claude', 'ghost', 'foreign', { issues: ['broken symlink'] }),
  skill('claude', 'learned', 'ignored'),
]
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
  {
    name: 'broken',
    workflow: 'broken',
    path: '/y',
    phases: 2,
    skills: 1,
    valid: false,
    errors: ['phase 2 names a skill that is not installed'],
    warnings: [],
  },
]
export const CONFIG = {
  version: 1,
  tools: { claude: 'on', codex: 'auto' },
  subagents: {
    claude: { heavy: 'opus', light: 'sonnet', trivial: 'haiku' },
    codex: { model: 'astra', heavy: 'xhigh', light: 'medium', trivial: 'low', max_threads: 6, max_depth: 1 },
  },
  review: { adversarial: 'auto' },
  guardrails: {
    never_delete: true,
    context_budget_tokens: 100000,
    preflight_checklist: true,
    plan_approval_gate: true,
    fix_approval_gate: false,
    hook_profile: 'standard',
    disabled_hooks: [],
  },
  paths: { obsidian_vaults: ['/vaults/notes'], sessions_dir: '~/.claude/sessions', backups_dir: '~/.agents/backups' },
  editor: '',
}
const CAPS = {
  items: {
    claude: { name: 'claude', present: true, version: '2.1.0 (Claude Code)', path: '/bin/claude', detail: '' },
    codex: { name: 'codex', present: true, version: 'codex-cli 0.1.0', path: '/bin/codex', detail: '' },
    gemini: { name: 'gemini', present: false, version: null, path: null, detail: 'not found on PATH' },
  },
  vaults: ['/vaults/notes', '/vaults/work'],
  nvm_versions: [],
}
const SKILL_MD = ['---', 'name: ship', '---', ...Array.from({ length: 20 }, (_, at) => `line ${at + 1} of the workflow`)].join('\n')

export type Answer = { exitCode: number; stdout: string; stderr: string }
export const json = (value: unknown): Answer => ({ exitCode: 0, stdout: JSON.stringify(value), stderr: '' })
export const text = (stdout: string): Answer => ({ exitCode: 0, stdout, stderr: '' })
export const bad = (stderr: string, exitCode = 2): Answer => ({ exitCode, stdout: '', stderr })

const CANNED: Record<string, Answer> = {
  'status --json': json(STATUS),
  'updates --json': json(UPDATES),
  'updates --json --fetch': json(UPDATES),
  'workflow list --json': json(WORKFLOWS),
  'workflow render ship': text(SKILL_MD),
  'doctor --json': json(DOCTOR),
  'caps --json': json(CAPS),
  'config list --json': json(CONFIG),
  'config path': text('/sandbox/user/.agents/config.json\n'),
  'tree beta --scope shared': text('shared/beta  (installed: ~/.agents/skills/beta)\nbeta/\n└── SKILL.md\n'),
}

// --------------------------------------------------------------------- world

export type WorldOptions = {
  canned?: Record<string, Answer>
  hasRepo?: boolean
  /** False makes config.json absent (the repo's own markers stay as `hasRepo` says). */
  hasConfig?: boolean
  refuse?: string[]
  /** False answers every ui.open with `isPlaced: false` (a terminal too narrow for an unasked pane). */
  placed?: boolean
}

/** What a `ui.open` carried, reduced to the fields the mod sets. */
export type OpenArgs = { id: string; title?: string; focus?: true; closeOnEscape?: true }

const MUTATING = /^(install|update|retire|relink|pull|apply|config (set|reset)|workflow (retire|push))\b/
const DONE = text('Plan (1 step(s)):\n  1. mkdir x\n  ok    mkdir x\nDone.\n')

/** Answers every call on `$` beneath the plugin and records what it was asked. */
export function world(on: On, options: WorldOptions = {}) {
  const answers = { ...CANNED, ...options.canned }
  const hasRepo = options.hasRepo !== false
  const hasConfig = options.hasConfig !== false
  const calls: { argv: string[]; cwd: string | undefined }[] = []
  const toasts: string[] = []
  const statuses: (string | undefined)[] = []
  const registered: string[] = []
  const opened: string[] = []
  const openArgs: OpenArgs[] = []
  let isPlaced = options.placed !== false
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
    return { value: e.path.endsWith('/config.json') ? hasConfig : hasRepo }
  })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('command.register', (_$, e) => {
    if (options.refuse?.includes(e.name)) return { deny: 'a name Claude Code ships' }
    registered.push(e.name)
    return { value: { command: e.name } }
  })
  on('ui.open', (_$, e) => {
    opened.push(e.id)
    openArgs.push({
      id: e.id,
      ...(e.title === undefined ? {} : { title: e.title }),
      ...(e.focus === undefined ? {} : { focus: e.focus }),
      ...(e.closeOnEscape === undefined ? {} : { closeOnEscape: e.closeOnEscape }),
    })
    return {
      value: isPlaced
        ? { isPlaced: true as const }
        : { isPlaced: false as const, reason: 'the terminal is 100 columns wide, the floor is 144' },
    }
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
  on('ui.scroll', () => ({}))
  /** Each call as `status --json`: what follows `python3 -m installer --repo <repo>`. */
  const commands = () => calls.map(call => call.argv.slice(5).join(' '))
  /** Changes what a command answers from now on, as the installer would after a write. */
  const answer = (command: string, value: Answer): void => {
    answers[command] = value
  }
  /** Changes what the next ui.open answers, as a widened terminal would. */
  const setPlaced = (value: boolean): void => {
    isPlaced = value
  }
  return { calls, toasts, statuses, registered, opened, openArgs, probed, clock, commands, answer, setPlaced }
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

export function mountPane($: Engine, surface: Surface, props = PANE, rows = 40) {
  return $.ui.mount({
    plugin: 'ai-suite',
    surface,
    component: 'Pane',
    props,
    requestId: 'ai-suite',
    viewport: { columns: 100, rows },
  })
}

export const BAND: RenderPropsOf['AbovePrompt'] = {
  hasSurvey: false,
  isWorking: false,
  maxRows: 10,
  bodyColumns: 100,
  scroll: { offset: 0, bodyRows: 9 },
  view: {},
}

/** Mounts the band above the prompt the way the engine draws it (it has no requestId of its own). */
export function mountBand($: Engine, surface: Surface, props = BAND) {
  return $.ui.mount({
    plugin: 'ai-suite',
    surface,
    component: 'AbovePrompt',
    props,
    viewport: { columns: 100, rows: 30 },
  })
}

/** The usual start of a view test: the world, `/skills`, the pane mounted on `surface` and pressed over to `view`. */
export async function openTo($: Engine, on: On, surface: Surface, options: WorldOptions = {}, view = 'overview') {
  const w = world(on, options)
  await $.command.run(run('skills'))
  const ui = await mountPane($, surface)
  if (view !== 'overview') await ui.press({ key: `view-${view}` })
  return { w, ui, after: (from: number) => w.commands().slice(from) }
}

type Query = { key?: string; type?: string; text?: string | RegExp }
export type Found = { key: string | undefined; text: string; props: Record<string, unknown> }
export type Drawn = {
  find: (query: Query) => Promise<Found | undefined>
  findAll: (query: Query) => Promise<Found[]>
}

export async function labelOf(ui: Drawn, key: string): Promise<unknown> {
  return (await ui.find({ key }))?.props.label
}

export async function textCount(ui: Drawn, pattern: RegExp): Promise<number> {
  return (await ui.findAll({ type: 'Text', text: pattern })).length
}

/** Whether the tab or chip labelled `label` is the chosen one (bold and underlined). */
export const isActive = async (ui: Drawn, label: string): Promise<boolean> =>
  (await ui.find({ type: 'Text', text: new RegExp(`^${label}$`) }))?.props.underline === true

/** The keys of every Button the drawing holds, in document order. */
export async function buttonKeys(ui: Drawn): Promise<string[]> {
  return (await ui.findAll({ type: 'Button' })).map(button => button.key ?? '')
}

/** Every Text the drawing holds, as plain strings. */
export async function allText(ui: Drawn): Promise<string[]> {
  return (await ui.findAll({ type: 'Text' })).map(item => item.text)
}

// ---------------------------------------------------------------- the drawn tree

/** What a mounted drawing hands back whole: an element as the tests read it (its `key` is in `props`). */
type Tree = { type?: string; props?: Record<string, unknown>; children?: unknown }
export type Whole = { drawn: () => Promise<unknown> }

const treeKey = (node: Tree): string => (typeof node.props?.key === 'string' ? node.props.key : '')

/** The elements among `value` (a child, a list of them, nested lists), strings and gaps left out. */
function elementsOf(value: unknown): Tree[] {
  if (Array.isArray(value)) return value.flatMap(elementsOf)
  return typeof value === 'object' && value !== null ? [value as Tree] : []
}

const childrenOf = (node: Tree): Tree[] => elementsOf(node.children ?? node.props?.children)

function walk(node: Tree, visit: (node: Tree) => void): void {
  visit(node)
  for (const child of childrenOf(node)) walk(child, visit)
}

/** The keys of every keyed Box and Button of the drawing, in document order. */
export async function keyedOrder(ui: Whole): Promise<string[]> {
  const keys: string[] = []
  walk((await ui.drawn()) as Tree, node => {
    const key = treeKey(node)
    if (key !== '' && (node.type === 'Box' || node.type === 'Button')) keys.push(key)
  })
  return keys
}

/** The keys of the children of the element that holds the keyed `key`, itself among them (an unkeyed child is ''). */
export async function siblingKeys(ui: Whole, key: string): Promise<string[]> {
  let found: string[] = []
  walk((await ui.drawn()) as Tree, node => {
    const keys = childrenOf(node).map(treeKey)
    if (keys.includes(key)) found = keys
  })
  return found
}

/** Every string the element `key` shows, anywhere below it. */
export async function textsUnder(ui: Whole, key: string): Promise<string[]> {
  const texts: string[] = []
  const collect = (value: unknown): void => {
    if (typeof value === 'string') texts.push(value)
    else if (Array.isArray(value)) value.forEach(collect)
    else if (typeof value === 'object' && value !== null) {
      const node = value as Tree
      collect(node.children ?? node.props?.children)
    }
  }
  walk((await ui.drawn()) as Tree, node => {
    if (treeKey(node) === key) collect(node.children ?? node.props?.children)
  })
  return texts
}

/** The props of the element `key`, when drawn. */
export async function propsOf(ui: Drawn, key: string): Promise<Record<string, unknown> | undefined> {
  return (await ui.find({ key }))?.props
}
