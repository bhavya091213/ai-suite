// Run with: claude plugin test mods/ai-suite
// The Part 7 views on both surfaces: Overview and Install (header, cards, filters, paging), the
// confirm card, the error callout, narrow panes, and the pure helpers. Installed, Updates, Workflows
// and Doctor are in manage.test.ts, Settings in settings.test.ts.
import { expect, test } from 'claude-code/testing'
import { runCli } from './cli'
import { parseConfig, parseStatus } from './parse'
import { barSegments, checkSummary, filterMissing, pageOf, scopeNumbers, statusLineText } from './summary'
import type { WorldOptions } from './testkit'
import {
  AT_REPO,
  PANE,
  REPO,
  STATUS,
  SURFACES,
  allText,
  bad,
  badgeText,
  buttonKeys,
  exact,
  isActive,
  isDesktop,
  json,
  labelOf,
  mountPane,
  openTo,
  run,
  skill,
  text,
  textCount,
  world,
} from './testkit'

/** Thirteen missing skills in all (the fixture's `dup` and twelve more) so the Install view pages. */
const MANY = [
  ...STATUS,
  ...Array.from({ length: 12 }, (_, at) =>
    skill(at % 2 === 0 ? 'shared' : 'claude', `extra-${at}`, 'not-installed'),
  ),
]
const WITH_MANY: WorldOptions = { canned: { 'status --json': json(MANY) } }

for (const surface of SURFACES) {
  test(`${surface}: the Overview has the header, a bar card per scope, what needs attention and the actions`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface)
    const desk = isDesktop(surface)

    // header: title and repo line, seven tabs (hotkeys in the terminal only), the status strip
    expect(await textCount(ui, desk ? /^Skills$/ : /^AI Suite · Skills$/)).toBe(1)
    expect(await textCount(ui, /^\/work\/ai-suite · main · 3 behind$/)).toBe(1)
    const tabs = ['overview o', 'install i', 'installed s', 'updates u', 'settings t', 'workflows w', 'doctor d']
    for (const tab of tabs) {
      const [view = '', hotkey = ''] = tab.split(' ')
      const found = await ui.find({ key: `view-${view}` })
      expect(found?.props).toMatchObject({ plain: true })
      expect(found?.props.hotkey).toBe(desk ? undefined : hotkey)
    }
    expect(await isActive(ui, 'Overview')).toBe(true)
    expect(await isActive(ui, 'Install')).toBe(false)
    expect((await ui.find({ type: 'Text', text: /^Overview$/ }))?.props.color).toBe(desk ? 'claude' : undefined)
    expect((await ui.find({ key: 'view-install' }))?.props.dimColor).toBe(desk ? true : undefined)
    expect(await textCount(ui, /^3\/4 installed$/)).toBe(1)
    expect(await textCount(ui, /^1 update$/)).toBe(1)
    expect(await textCount(ui, /^2 issues$/)).toBe(1)
    expect(await textCount(ui, exact('●'))).toBeGreaterThanOrEqual(desk ? 3 : 0)

    // one card per scope: a bar the width of the card, then the numbers; never a █ or ░ slab
    expect((await allText(ui)).join('')).not.toMatch(/[█░]/)
    expect(await textCount(ui, /^Nothing is offered in this scope\.$/)).toBe(1)
    if (desk) {
      const bars = await ui.findAll({ type: 'Svg' })
      expect(bars.map(each => each.props.alt)).toEqual(['2 of 3 installed', '1 of 1 installed'])
      // the coloured numbers under the bars (the dim `4` is the attention card's count)
      const numbers = (await ui.findAll({ type: 'Text', text: /^\d$/ })).filter(item => item.props.dimColor !== true)
      const colours = numbers.map(item => item.props.color)
      expect(colours).toEqual(['success', 'warning', 'subtle', 'error', 'success', 'subtle', 'subtle', 'error'])
      expect((await ui.findAll({ type: 'Text', text: /^installed$/ })).every(item => item.props.dimColor === true)).toBe(true)
    } else {
      expect(await textCount(ui, /^1 installed · 1 modified · 1 missing · 1 problem$/)).toBe(1)
      expect(await textCount(ui, /^1 installed · 0 modified · 0 missing · 1 problem$/)).toBe(1)
      const runs = async (glyph: string, color?: string) =>
        (await ui.findAll({ type: 'Text', text: new RegExp(`^${glyph}+$`) }))
          .filter(item => color === undefined || item.props.color === color)
          .map(item => item.text.length)
      expect(await runs('━', 'success')).toEqual([32, 96])
      expect(await runs('━', 'warning')).toEqual([32])
      expect(await runs('─')).toEqual([32])
    }

    // needs attention, in order, each with a button that jumps to the right view
    const items = [
      '2 skills have problems to repair',
      '3 commits behind · 1 skill changed upstream',
      '1 skill is modified locally',
      '1 skill is not installed yet',
    ]
    const lines = await allText(ui)
    expect(lines.map(line => line.replace(/^• /, '')).filter(line => items.includes(line))).toEqual(items)
    expect(lines.filter(line => line.startsWith('• '))).toHaveLength(desk ? 0 : 4)
    expect(await labelOf(ui, 'overview-install')).toBe('Install 1 missing')
    expect((await ui.find({ key: 'overview-install' }))?.props.variant).toBe('primary')
    expect(await labelOf(ui, 'overview-fetch')).toBe('Check for updates')
    expect(await labelOf(ui, 'overview-setup')).toBeUndefined()

    await ui.press({ key: 'attention-problems' })
    expect(await isActive(ui, 'Installed')).toBe(true)
    expect(await isActive(ui, 'Problems')).toBe(true)
    await ui.unmount()
  })

  test(`${surface}: Install has filter chips, a name filter, cards of five and an Install button per card`, AT_REPO, async ($, on) => {
    const { w, ui, after } = await openTo($, on, surface, WITH_MANY, 'install')

    expect(await labelOf(ui, 'install-scope:claude')).toBe('Claude')
    expect(await isActive(ui, 'All')).toBe(true)
    expect((await ui.find({ key: 'install-query' }))?.props.placeholder).toBe('Filter by name…')
    expect((await buttonKeys(ui)).filter(key => key.startsWith('install:'))).toEqual([
      'install:shared/dup',
      'install:shared/extra-0',
      'install:claude/extra-1',
      'install:shared/extra-2',
      'install:claude/extra-3',
    ])
    expect(await textCount(ui, /^Showing 1-5 of 13$/)).toBe(1)
    expect(await textCount(ui, exact(badgeText(surface, '· missing')))).toBe(5)
    expect(await textCount(ui, /^dup skill$/)).toBe(1)
    expect(await labelOf(ui, 'install:shared/dup')).toBe('Install dup')
    expect(await labelOf(ui, 'install-all')).toBe('Install all 13')
    // a card's main action is primary on the desktop only; the footer's is primary everywhere
    expect((await ui.find({ key: 'install:shared/dup' }))?.props.variant).toBe(isDesktop(surface) ? 'primary' : undefined)
    expect((await ui.find({ key: 'install-all' }))?.props.variant).toBe('primary')

    await ui.press({ key: 'next:install' })
    expect(await textCount(ui, /^Showing 6-10 of 13$/)).toBe(1)
    expect(await labelOf(ui, 'install:claude/extra-5')).toBe('Install extra-5')
    expect(await labelOf(ui, 'install:shared/dup')).toBeUndefined()
    await ui.press({ key: 'prev:install' })
    expect(await labelOf(ui, 'install:shared/dup')).toBe('Install dup')

    // the name filter narrows the cards, a chip narrows them by scope
    await ui.input({ key: 'install-query', text: 'extra-1', kind: 'change' })
    expect((await buttonKeys(ui)).filter(key => key.startsWith('install:'))).toEqual([
      'install:claude/extra-1',
      'install:shared/extra-10',
      'install:claude/extra-11',
    ])
    expect(await labelOf(ui, 'install-all')).toBe('Install all 3')
    await ui.input({ key: 'install-query', text: '', kind: 'change' })
    await ui.press({ key: 'install-scope:claude' })
    expect(await isActive(ui, 'Claude')).toBe(true)
    expect(await textCount(ui, /^Showing 1-5 of 6$/)).toBe(1)

    const from = w.calls.length
    await ui.press({ key: 'install:claude/extra-1' })
    expect(after(from)[0]).toBe('install extra-1 --scope claude --yes')
    expect(await textCount(ui, /^Installed claude\/extra-1\.$/)).toBe(1)
    expect(w.toasts).toContain('Installed claude/extra-1.')
    await ui.unmount()
  })

  test(`${surface}: Install all asks first: other presses are ignored, n cancels, y installs`, AT_REPO, async ($, on) => {
    const { w, ui, after } = await openTo($, on, surface, WITH_MANY, 'install')
    const from = w.calls.length

    await ui.press({ key: 'install-all' })
    expect(after(from)).toEqual([])
    expect(await textCount(ui, /^Install 13 missing skills\?$/)).toBe(1)
    expect(await textCount(ui, /existing files are never overwritten/)).toBe(1)
    expect(await labelOf(ui, 'confirm-yes')).toBe('Yes, install 13')
    const yes = (await ui.find({ key: 'confirm-yes' }))?.props
    const no = (await ui.find({ key: 'confirm-no' }))?.props
    if (isDesktop(surface)) {
      // native buttons: a primary answer and a plain Cancel, no key caps
      expect(yes).toMatchObject({ variant: 'primary' })
      expect([yes?.hotkey, yes?.plain, no?.hotkey, no?.plain]).toEqual([undefined, undefined, undefined, undefined])
      expect(no?.label).toBe('Cancel')
    } else {
      expect(yes).toMatchObject({ hotkey: 'y', plain: true })
      expect(no).toMatchObject({ hotkey: 'n', label: 'Cancel' })
    }
    expect((await ui.find({ key: 'confirm' }))?.props.borderColor).toBe('warning')

    // every other press is ignored while the card is up
    await ui.press({ key: 'view-updates' })
    await ui.press({ key: 'install:shared/dup' })
    expect(after(from)).toEqual([])
    expect(await isActive(ui, 'Install')).toBe(true)

    await ui.press({ key: 'confirm-no' })
    expect(await labelOf(ui, 'confirm-yes')).toBeUndefined()
    expect(after(from)).toEqual([])

    await ui.press({ key: 'install-all' })
    await ui.press({ key: 'confirm-yes' })
    expect(after(from).slice(0, 2)).toEqual([
      `install dup ${[0, 2, 4, 6, 8, 10].map(at => `extra-${at}`).join(' ')} --scope shared --yes`,
      `install ${[1, 3, 5, 7, 9, 11].map(at => `extra-${at}`).join(' ')} --scope claude --yes`,
    ])
    expect(await labelOf(ui, 'confirm-yes')).toBeUndefined()
    await ui.unmount()
  })

  test(`${surface}: a failure is a red callout and a toast until the next action; nothing to do is a note`, AT_REPO, async ($, on) => {
    const canned = {
      'install dup --scope shared --yes': bad('error: unknown skill: dup'),
      'install extra-0 --scope shared --yes': text('shared/extra-0: skipped - already installed\nNothing to do.\n'),
    }
    const { w, ui } = await openTo($, on, surface, { canned: { ...WITH_MANY.canned, ...canned } }, 'install')

    await ui.press({ key: 'install:shared/dup' })
    expect((await ui.find({ key: 'callout:Something went wrong' }))?.props.borderColor).toBe('error')
    expect(await textCount(ui, /^Install shared\/dup failed: error: unknown skill: dup$/)).toBe(1)
    expect(w.toasts.some(line => line.includes('error: unknown skill: dup'))).toBe(true)
    expect(await labelOf(ui, 'install:shared/dup')).toBe('Install dup')

    await ui.press({ key: 'install:shared/extra-0' })
    expect(await ui.find({ key: 'callout:Something went wrong' })).toBeUndefined()
    expect(await textCount(ui, /^Nothing to do\. · shared\/extra-0: skipped - already installed$/)).toBe(1)
    await ui.unmount()
  })

  test(`${surface}: every view draws the header and a card, and in a narrow pane no line is wider than the pane`, AT_REPO, async ($, on) => {
    world(on, WITH_MANY)
    await $.command.run(run('skills'))
    const ui = await mountPane($, surface, { ...PANE, bodyColumns: 40 })
    for (const view of ['overview', 'install', 'installed', 'updates', 'settings', 'workflows', 'doctor']) {
      await ui.press({ key: `view-${view}` })
      expect(await textCount(ui, isDesktop(surface) ? /^Skills$/ : /^AI Suite · Skills$/)).toBe(1)
      expect((await ui.findAll({ type: 'Box' })).some(box => box.props.borderStyle === 'round')).toBe(true)
      const widest = Math.max(...(await allText(ui)).map(line => line.length))
      expect(widest).toBeLessThanOrEqual(40)
    }
    await ui.unmount()
  })
}

const VIEWS = ['overview', 'install', 'installed', 'updates', 'settings', 'workflows', 'doctor'] as const

for (const surface of ['desktop', 'vscode'] as const) {
  test(`${surface}: progress is an Svg whose alt names the counts, and the tabs carry no hotkey`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface)

    const bars = await ui.findAll({ type: 'Svg' })
    expect(bars.map(each => each.props.alt)).toEqual(['2 of 3 installed', '1 of 1 installed'])
    for (const each of bars) {
      // 8 px high, as wide as its card: no width prop, the markup stretches over its own viewBox
      expect(each.props.height).toBe(8)
      expect(each.props.width).toBeUndefined()
      expect(each.props.source).toContain('viewBox="0 0 1000 8" width="100%" preserveAspectRatio="none"')
    }
    // shared: 2 of 3 present, 1 of them modified: a track, the filled part, the modified share over its end
    const source = String(bars[0]?.props.source)
    expect(source).toContain('<rect width="1000" height="8" rx="4" fill="#808080" fill-opacity="0.25"/>')
    expect(source).toContain('<rect width="667" height="8" rx="4" fill="#3fa65b"/>')
    expect(source).toContain('<rect x="334" width="333" height="8" rx="4" fill="#e0a526"/>')
    expect(String(bars[1]?.props.source)).not.toContain('#e0a526')

    const tabs = await ui.findAll({ type: 'Button', text: /^(Overview|Install|Installed|Updates|Settings|Workflows|Doctor)$/ })
    expect(tabs).toHaveLength(7)
    for (const tab of tabs) {
      expect(tab.props.hotkey).toBeUndefined()
      expect(tab.props.plain).toBe(true)
    }
    for (const view of VIEWS) {
      await ui.press({ key: `view-${view}` })
      const joined = (await allText(ui)).join('')
      expect(joined).not.toMatch(/[█░━─]/)
      expect((await ui.find({ key: `view-${view}` }))?.props.hotkey).toBeUndefined()
    }
    await ui.unmount()
  })
}

test('terminal: no view draws a █, bars are ━ and ─, the tab buttons have hotkeys and there is no Svg', AT_REPO, async ($, on) => {
  const { ui } = await openTo($, on, 'terminal')

  expect(await ui.findAll({ type: 'Svg' })).toHaveLength(0)
  const hotkeys = await Promise.all(
    VIEWS.map(async view => (await ui.find({ key: `view-${view}` }))?.props.hotkey),
  )
  expect(hotkeys).toEqual(['o', 'i', 's', 'u', 't', 'w', 'd'])
  expect((await ui.findAll({ type: 'Text', text: /^[━─]+$/ })).length).toBeGreaterThan(0)
  for (const view of VIEWS) {
    await ui.press({ key: `view-${view}` })
    expect((await allText(ui)).join('')).not.toMatch(/[█░]/)
  }
  await ui.unmount()
})

test('a surface with no text fields gets a one-line note instead of the pane', AT_REPO, async ($, on) => {
  world(on)
  const ui = await $.ui.mount({
    plugin: 'ai-suite',
    surface: 'mobile',
    component: 'Pane',
    props: PANE,
    requestId: 'ai-suite',
    viewport: { columns: 60, rows: 30 },
  })
  expect(await textCount(ui, /^The Skills pane needs the terminal or the desktop app\.$/)).toBe(1)
  await ui.unmount()
})

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

test('parsers tolerate junk, config flattens to dotted keys, and the summaries read well', () => {
  expect(parseStatus({})).toBeNull()
  expect(parseStatus([1, null, { scope: 'shared' }, { scope: 'shared', name: 'a', state: 'installed' }])).toHaveLength(1)
  expect(parseConfig([])).toBeNull()
  expect(
    parseConfig({ tools: { claude: 'on' }, guardrails: { never_delete: false, disabled_hooks: ['a', 'b'] }, paths: { obsidian_vaults: [] }, editor: '' }),
  ).toEqual({
    'tools.claude': 'on',
    'guardrails.never_delete': 'off',
    'guardrails.disabled_hooks': 'a,b',
    'paths.obsidian_vaults': '',
    editor: '',
  })
  expect(pageOf([1, 2, 3, 4, 5], 9, 2)).toEqual({ items: [5], page: 2, pages: 3, hidden: 0 })
  // a bar divides into installed, modified (drawn after) and missing; a skill that is there gets a unit
  expect(barSegments(1, 0, 4, 8)).toEqual({ ok: 2, mod: 0, rest: 6 })
  expect(barSegments(0, 0, 0, 4)).toEqual({ ok: 0, mod: 0, rest: 4 })
  expect(barSegments(1, 1, 3, 96)).toEqual({ ok: 32, mod: 32, rest: 32 })
  expect(barSegments(0, 1, 5000, 10)).toEqual({ ok: 0, mod: 1, rest: 9 })
  expect(scopeNumbers({ scope: 'shared', installed: 57, modified: 6, missing: 26, problems: 0 })).toBe(
    '57 installed · 6 modified · 26 missing · 0 problems',
  )
  const rows = parseStatus(MANY) ?? []
  expect(filterMissing(rows, { installScope: 'claude', installQuery: 'EXTRA-3', installTag: 'all' }).map(row => row.name)).toEqual(['extra-3'])
  expect(statusLineText({ data: null, fetchedAt: null, error: null }, { data: null, fetchedAt: null, error: null })).toBeUndefined()
  expect(checkSummary({ doctor: null, doctorError: 'x', updates: null, updatesError: 'y' })).toBe(
    'skills check: doctor failed (x) · updates failed (y)',
  )
})
