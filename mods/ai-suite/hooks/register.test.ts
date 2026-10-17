// Run with: claude plugin test mods/ai-suite
// The Part 6 tests: session.start, repo resolution and the commands. The pane's views are tested
// in views.test.ts and settings.test.ts. `process.run` is answered per argv with canned JSON (testkit.ts).
import { expect, test } from 'claude-code/testing'
import { grandparent, resolveRepo } from './cli'
import {
  AT_REPO,
  PY,
  REPO,
  SURFACES,
  bad,
  flush,
  mountPane,
  run,
  textCount,
  world,
} from './testkit'

// -------------------------------------------------------------- session.start

test('session.start registers /skills and /skills-check and sets the status line', AT_REPO, async ($, on) => {
  const w = world(on)
  await $.session.start({ cwd: '/work', surface: 'terminal', isInteractive: true })
  await flush(w.clock)

  expect(w.registered).toContain('skills')
  expect(w.registered).toContain('skills-check')
  expect(w.statuses).toContain('skills 3/4 · 1 update · 2 issues')
  // no network at start: status and a plain updates read, never --fetch
  expect(w.commands()).toEqual(['status --json', 'updates --json'])
  expect(w.calls[0]?.argv.slice(0, 5)).toEqual(PY)
  expect(w.calls[0]?.cwd).toBe(REPO)
})

test('checkOnStart off: commands are registered but nothing runs', { options: { checkOnStart: false } }, async ($, on) => {
  const w = world(on)
  await $.session.start({ cwd: '/work', surface: 'terminal', isInteractive: true })
  await flush(w.clock)

  expect(w.registered).toContain('skills')
  expect(w.calls).toHaveLength(0)
  expect(w.statuses).toHaveLength(0)
})

test('a refused command name does not stop the others or the start check', AT_REPO, async ($, on) => {
  const w = world(on, { refuse: ['skills'] })
  await $.session.start({ cwd: '/work', surface: 'terminal', isInteractive: true })
  await flush(w.clock)

  expect(w.registered).toEqual(['skills-check', 'ai-suite'])
  expect(w.statuses).toContain('skills 3/4 · 1 update · 2 issues')
})

test('a failing start check shows a quiet status and no toast', AT_REPO, async ($, on) => {
  const w = world(on, { canned: { 'status --json': bad('error: boom', 1) } })
  await $.session.start({ cwd: '/work', surface: 'terminal', isInteractive: true })
  await flush(w.clock)

  expect(w.statuses).toContain('skills: check failed (see /skills)')
  expect(w.toasts).toHaveLength(0)
  expect(w.commands()).toEqual(['status --json'])
})

// ----------------------------------------------------------- repo resolution

test('repoPath unset resolves the plugin folder grandparent (exact, with a fake $)', async () => {
  const probed: string[] = []
  const fake = {
    plugin: { name: 'ai-suite', root: '/work/ai-suite/mods/ai-suite' },
    env: { get: async () => '/sandbox/user' },
    fs: { exists: async (path: string) => { probed.push(path); return true } },
    session: { cwd: async () => '/elsewhere' },
  }
  const settings = { repoPath: '', python: 'python3', checkOnStart: true }
  // @ts-expect-error a partial `$` is enough for resolveRepo
  const found = await resolveRepo(fake, settings)

  expect(found).toEqual({ ok: true, repo: '/work/ai-suite', shown: '/work/ai-suite', home: '/sandbox/user' })
  expect(probed).toEqual(['/work/ai-suite/install.sh', '/work/ai-suite/installer'])
  expect(grandparent('/a/b/c/')).toBe('/a')
  expect(grandparent('/mods/ai-suite')).toBe('/')
})

test('repoPath set: ~ expands, relative resolves from the session, and a wrong folder is explained', async () => {
  const make = (has: boolean) => ({
    plugin: { name: 'ai-suite', root: '/somewhere/else/ai-suite' },
    env: { get: async () => '/sandbox/user' },
    fs: { exists: async () => has },
    session: { cwd: async () => '/work' },
  })
  const settings = (repoPath: string) => ({ repoPath, python: 'python3', checkOnStart: true })
  // @ts-expect-error partial `$`
  const home = await resolveRepo(make(true), settings('~/code/ai-suite'))
  // @ts-expect-error partial `$`
  const relative = await resolveRepo(make(true), settings('clone'))
  // @ts-expect-error partial `$`
  const wrong = await resolveRepo(make(false), settings('/nope'))

  expect(home).toMatchObject({ ok: true, repo: '/sandbox/user/code/ai-suite', shown: '~/code/ai-suite' })
  expect(relative).toMatchObject({ ok: true, repo: '/work/clone' })
  expect(wrong).toMatchObject({ ok: false })
  expect(wrong.ok ? '' : wrong.error).toContain('repoPath /nope does not look like the ai-suite repo')
  expect(wrong.ok ? '' : wrong.error).toContain('install.sh and installer/')
})

/** Runs resolveRepo against a fake `$`: `present` lists the paths that exist, `env` the variables set. */
async function resolveWith(
  present: readonly string[],
  env: Record<string, string>,
  repoPath = '',
) {
  const probed: string[] = []
  const fake = {
    plugin: { name: 'ai-suite', root: '/sandbox/user/.claude/plugins/cache/ai-suite/ai-suite/0.1.0' },
    env: { get: async (name: string) => ({ HOME: '/sandbox/user', ...env })[name] },
    fs: { exists: async (path: string) => { probed.push(path); return present.includes(path) } },
    session: { cwd: async () => '/work' },
  }
  // @ts-expect-error a partial `$` is enough for resolveRepo
  const found = await resolveRepo(fake, { repoPath, python: 'python3', checkOnStart: true })
  return { found, probed }
}

const holds = (repo: string) => [`${repo}/install.sh`, `${repo}/installer`]
const CLONE = '/sandbox/user/.claude/plugins/marketplaces/ai-suite'

test('with the grandparent not the repo, the marketplace clone under ~/.claude/plugins resolves', async () => {
  const { found, probed } = await resolveWith(holds(CLONE), {})

  expect(found).toEqual({ ok: true, repo: CLONE, shown: '~/.claude/plugins/marketplaces/ai-suite', home: '/sandbox/user' })
  // the grandparent is tried first, then the clone (install.sh and installer/ both)
  expect(probed.at(-2)).toBe(`${CLONE}/install.sh`)
  expect(probed.at(-1)).toBe(`${CLONE}/installer`)
  expect(probed[0]).toBe('/sandbox/user/.claude/plugins/cache/ai-suite/install.sh')
})

test('the marketplace clone is only a fallback: a grandparent that holds the markers wins', async () => {
  const grand = '/sandbox/user/.claude/plugins/cache/ai-suite'
  const { found, probed } = await resolveWith([...holds(grand), ...holds(CLONE)], {})

  expect(found).toMatchObject({ ok: true, repo: grand })
  expect(probed.some(path => path.startsWith(CLONE))).toBe(false)
})

test('CLAUDE_CODE_PLUGIN_CACHE_DIR moves the plugins root and beats CLAUDE_CONFIG_DIR', async () => {
  const cache = await resolveWith(holds('/opt/plugins/marketplaces/ai-suite'), {
    CLAUDE_CODE_PLUGIN_CACHE_DIR: '/opt/plugins',
    CLAUDE_CONFIG_DIR: '/cfg',
  })
  const config = await resolveWith(holds('/cfg/plugins/marketplaces/ai-suite'), { CLAUDE_CONFIG_DIR: '/cfg' })
  const tilde = await resolveWith(holds('/sandbox/user/p/marketplaces/ai-suite'), { CLAUDE_CODE_PLUGIN_CACHE_DIR: '~/p' })

  expect(cache.found).toMatchObject({ ok: true, repo: '/opt/plugins/marketplaces/ai-suite' })
  expect(cache.probed.some(path => path.startsWith('/cfg') || path.includes('.claude/plugins/marketplaces'))).toBe(false)
  expect(config.found).toMatchObject({ ok: true, repo: '/cfg/plugins/marketplaces/ai-suite' })
  expect(tilde.found).toMatchObject({ ok: true, repo: '/sandbox/user/p/marketplaces/ai-suite', shown: '~/p/marketplaces/ai-suite' })
})

test('when none of the three places holds the markers, the message names all three', async () => {
  const { found } = await resolveWith(['/sandbox/user/.claude/plugins/marketplaces/ai-suite/install.sh'], {})

  expect(found).toMatchObject({ ok: false })
  const error = found.ok ? '' : found.error
  expect(error).toContain('repoPath (not set)')
  expect(error).toContain("this plugin's grandparent ~/.claude/plugins/cache/ai-suite (missing install.sh and installer/)")
  expect(error).toContain('the marketplace clone ~/.claude/plugins/marketplaces/ai-suite (missing installer/)')
  expect(error).toContain('claude --plugin-dir mods/ai-suite')
})

test('an explicit repoPath that is wrong is not rescued by the marketplace clone', async () => {
  const { found, probed } = await resolveWith(holds(CLONE), {}, '/nope')

  expect(found).toMatchObject({ ok: false })
  expect(found.ok ? '' : found.error).toContain('repoPath /nope does not look like the ai-suite repo')
  expect(probed.some(path => path.startsWith(CLONE))).toBe(false)
})

test('through the pane: the repo argument is the grandparent and install.sh plus installer/ are probed', async ($, on) => {
  const w = world(on)
  await $.command.run(run('skills'))

  const repo = w.calls[0]?.argv[4] ?? ''
  expect(repo.startsWith('/')).toBe(true)
  expect(repo.endsWith('/mods/ai-suite')).toBe(false)
  expect(w.probed).toContain(`${repo}/install.sh`)
  expect(w.probed).toContain(`${repo}/installer`)
  expect(w.calls[0]?.cwd).toBe(repo)
})

test('an explicit repoPath is used as the --repo argument and as cwd', { options: { repoPath: '~/code/ai-suite', python: 'py3' } }, async ($, on) => {
  const w = world(on)
  await $.command.run(run('skills'))

  expect(w.calls[0]?.argv.slice(0, 5)).toEqual(['py3', '-m', 'installer', '--repo', '/sandbox/user/code/ai-suite'])
  expect(w.calls[0]?.cwd).toBe('/sandbox/user/code/ai-suite')
})

test('a folder that is not the repo: a clear message, a toast, and nothing is run', AT_REPO, async ($, on) => {
  const w = world(on, { hasRepo: false })
  const result = await $.command.run(run('skills'))

  expect(w.calls).toHaveLength(0)
  expect(w.toasts[0]).toContain('does not look like the ai-suite repo')
  expect(result.text).toBe('Skills pane opened.')
  for (const surface of SURFACES) {
    const ui = await mountPane($, surface)
    expect(await textCount(ui, /does not look like the ai-suite repo/)).toBeGreaterThan(0)
    await ui.unmount()
  }
})

// ------------------------------------------------------------------ commands

test('/skills opens the pane and loads the overview; /ai-suite does the same', AT_REPO, async ($, on) => {
  const w = world(on)
  const first = await $.command.run(run('skills'))
  const second = await $.command.run(run('ai-suite'))

  expect(first.text).toBe('Skills pane opened.')
  expect(second.text).toBe('Skills pane opened.')
  expect(w.opened).toEqual(['ai-suite', 'ai-suite'])
  // the second open found everything loaded already
  expect(w.commands()).toEqual(['status --json', 'updates --json', 'config path'])
})

test('/skills-check runs doctor then a fetching updates read and toasts one line', AT_REPO, async ($, on) => {
  const w = world(on)
  const result = await $.command.run(run('skills-check'))

  expect(w.commands()).toEqual(['doctor --json', 'updates --json --fetch'])
  const line = 'skills check: doctor ok, 1 warning · 3 commits behind · 1 skill changed upstream'
  expect(result.text).toBe(line)
  expect(w.toasts).toEqual([line])
})

test('/skills-check accepts doctor exit 1 with JSON, and reports a failing read', AT_REPO, async ($, on) => {
  const blocked = { checks: [{ name: 'python', state: 'blocker', text: 'too old' }], blockers: 1 }
  const w = world(on, {
    canned: {
      'doctor --json': { exitCode: 1, stdout: JSON.stringify(blocked), stderr: '' },
      'updates --json --fetch': bad('error: fetch failed', 1),
    },
  })
  const result = await $.command.run(run('skills-check'))

  expect(result.text).toBe('skills check: doctor: 1 blocker · updates failed (error: fetch failed)')
  expect(w.toasts).toEqual([result.text])
})
