// Run with: claude plugin test mods/ai-suite
// The Updates / Install-all / Apply flows, the smaller views, paging, and the pure helpers.
import { expect, test } from 'claude-code/testing'
import { parseStatus, runCli } from './cli'
import { checkSummary, pageOf, statusLineText } from './summary'
import {
  AT_REPO,
  PANE,
  REPO,
  SURFACES,
  json,
  labelOf,
  mountPane,
  run,
  text,
  textCount,
  world,
} from './testkit'

for (const surface of SURFACES) {
  test(`${surface}: Pull, Update changed, Install all missing and Apply are two-step`, AT_REPO, async ($, on) => {
    const w = world(on)
    await $.command.run(run('skills'))
    const ui = await mountPane($, surface)
    const after = (from: number) => w.commands().slice(from)

    await ui.press({ key: 'view-updates' })
    expect(await textCount(ui, /^Commits behind \(3\)$/)).toBe(1)
    expect(await textCount(ui, /shared\/beta \(1 files\)/)).toBe(1)

    let from = w.calls.length
    await ui.press({ key: 'pull' })
    expect(after(from)).toEqual([])
    await ui.press({ key: 'pull' })
    expect(after(from)[0]).toBe('pull --yes')

    from = w.calls.length
    await ui.press({ key: 'update-changed' })
    expect(after(from)).toEqual([])
    await ui.press({ key: 'update-changed' })
    expect(after(from)[0]).toBe('update beta --scope shared --yes')

    from = w.calls.length
    await ui.press({ key: 'fetch' })
    expect(after(from)).toEqual(['updates --json --fetch'])

    await ui.press({ key: 'view-install' })
    from = w.calls.length
    await ui.press({ key: 'install-all' })
    expect(after(from)).toEqual([])
    await ui.press({ key: 'install-all' })
    expect(after(from).slice(0, 2)).toEqual([
      'install dup --scope shared --yes',
      'install nometa --scope claude --yes',
    ])

    from = w.calls.length
    await ui.press({ key: 'view-overview' })
    await ui.press({ key: 'apply' })
    expect(after(from)).not.toContain('apply --yes')
    await ui.press({ key: 'apply' })
    expect(after(from)).toContain('apply --yes')
    await ui.unmount()
  })

  test(`${surface}: a command that had nothing to do says so instead of claiming success`, AT_REPO, async ($, on) => {
    const skipped = text('shared/dup: skipped - already installed\nNothing to do.\n')
    world(on, { canned: { 'install dup --scope shared --yes': skipped } })
    await $.command.run(run('skills'))
    const ui = await mountPane($, surface)
    await ui.press({ key: 'view-install' })
    await ui.press({ key: 'install:shared/dup' })

    expect(await textCount(ui, /^Nothing to do\. · shared\/dup: skipped - already installed$/)).toBe(1)
    await ui.unmount()
  })

  test(`${surface}: Workflows and Doctor rows, and lists are paged to the viewport`, AT_REPO, async ($, on) => {
    const many = Array.from({ length: 30 }, (_, at) => ({
      scope: 'shared', name: `skill-${at}`, state: 'not-installed', installed: 'no', description: 'd',
    }))
    world(on, { canned: { 'list --json': json(many) } })
    await $.command.run(run('skills'))
    const ui = await mountPane($, surface, { ...PANE, scroll: { offset: 0, bodyRows: 14 } }, 14)

    await ui.press({ key: 'view-workflows' })
    expect(await textCount(ui, /^ship {2}3 phases · 5 skills · valid$/)).toBe(1)
    await ui.press({ key: 'view-doctor' })
    expect(await textCount(ui, /^no blockers · 1 warning$/)).toBe(1)
    expect(await textCount(ui, /^\[warn\] git: not a checkout$/)).toBe(1)

    await ui.press({ key: 'view-install' })
    expect(await textCount(ui, /^30 not installed$/)).toBe(1)
    expect(await labelOf(ui, 'install:shared/skill-0')).toBe('Install')
    expect(await labelOf(ui, 'install:shared/skill-29')).toBeUndefined()
    expect(await textCount(ui, /^page 1\/6 · 25 more$/)).toBe(1)
    await ui.press({ key: 'page-next' })
    expect(await labelOf(ui, 'install:shared/skill-0')).toBeUndefined()
    expect(await labelOf(ui, 'install:shared/skill-5')).toBe('Install')
    await ui.unmount()
  })
}

// --------------------------------------------------------------- pure helpers

test('runCli turns a failure into a value and keeps the first line of stderr', async () => {
  const run = async () => ({
    exitCode: 2,
    stdout: '',
    stderr: 'error: first line\nsecond line',
    isStdoutTruncated: false,
    isStderrTruncated: false,
  })
  const cfg = { repo: REPO, python: 'python3', home: '/sandbox/user' }
  // @ts-expect-error a partial `$` is enough for runCli
  const failed = await runCli({ process: { run } }, cfg, ['status', '--json'])
  expect(failed).toEqual({ ok: false, error: 'error: first line' })

  const broken = async () => {
    throw new Error('spawn python3 ENOENT')
  }
  // @ts-expect-error a partial `$` is enough for runCli
  const missing = await runCli({ process: { run: broken } }, cfg, ['status', '--json'])
  expect(missing).toEqual({ ok: false, error: 'could not run python3: spawn python3 ENOENT' })
})

test('parsers tolerate junk, and the summaries read well', async () => {
  expect(parseStatus({})).toBeNull()
  expect(parseStatus([1, null, { scope: 'shared' }, { scope: 'shared', name: 'a', state: 'installed' }])).toHaveLength(1)
  expect(pageOf([1, 2, 3, 4, 5], 9, 2)).toEqual({ items: [5], page: 2, pages: 3, hidden: 0 })
  expect(statusLineText({ data: null, fetchedAt: null, error: null }, { data: null, fetchedAt: null, error: null })).toBeUndefined()
  expect(checkSummary({ doctor: null, doctorError: 'x', updates: null, updatesError: 'y' })).toBe(
    'skills check: doctor failed (x) · updates failed (y)',
  )
})
