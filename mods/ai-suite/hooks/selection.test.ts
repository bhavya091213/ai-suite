// Run with: claude plugin test mods/ai-suite
// Ticking skills on the Install and Installed views on both surfaces: the tick box and the
// border, the selection bar and its counts, Select all shown across pages, the filters keeping the
// selection, a rescan dropping skills that are gone, and the bulk actions (one call per scope, in
// order, stopping at the first failure). Where a confirm card is drawn is in placement.test.ts.
import { expect, test } from 'claude-code/testing'
import {
  AT_REPO,
  STATUS,
  SURFACES,
  bad,
  buttonKeys,
  isDesktop,
  json,
  labelOf,
  openTo,
  propsOf,
  skill,
  textCount,
  textsUnder,
} from './testkit'
import type { WorldOptions } from './testkit'

/** Thirteen missing skills in all (`dup` and twelve more, alternating shared and claude). */
const MISSING = [
  ...STATUS,
  ...Array.from({ length: 12 }, (_, at) => skill(at % 2 === 0 ? 'shared' : 'claude', `extra-${at}`, 'not-installed')),
]
const INSTALL: WorldOptions = { canned: { 'status --json': json(MISSING) } }

/** Thirteen on disk: the fixture's five (the last is tool-managed) and eight more, alternating shared and claude. */
const HAVE = Array.from({ length: 8 }, (_, at) => skill(at % 2 === 0 ? 'shared' : 'claude', `have-${at}`, 'installed'))
const ON_DISK = [...STATUS, ...HAVE]
const INSTALLED: WorldOptions = { canned: { 'status --json': json(ON_DISK) } }

/** The retire-able ones in the rows' order: everything on disk but the tool-managed `learned`. */
const SHARED = ['alpha', 'beta', 'have-0', 'have-2', 'have-4', 'have-6']
const CLAUDE = ['gamma', 'ghost', 'have-1', 'have-3', 'have-5', 'have-7']
const RETIRE_SHARED = `retire ${SHARED.join(' ')} --scope shared --yes`
const RETIRE_CLAUDE = `retire ${CLAUDE.join(' ')} --scope claude --yes`

type Opened = Awaited<ReturnType<typeof openTo>>['ui']

const ticked = async (ui: Opened) =>
  (await ui.findAll({ type: 'Button', text: /^☑$/ })).map(button => button.key)
const selects = async (ui: Opened) => (await buttonKeys(ui)).filter(key => key.startsWith('select:'))
const tick = async (ui: Opened, ...ids: string[]) => {
  for (const id of ids) await ui.press({ key: `select:${id}` })
}
const selectAll = async (ui: Opened, list: string) => ui.press({ key: `select-all:${list}` })

for (const surface of SURFACES) {
  test(`${surface}: every card has a tick box: a press flips ☐ to ☑ and gives the card Claude's border`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, INSTALL, 'install')

    expect(await selects(ui)).toEqual(
      ['shared/dup', 'shared/extra-0', 'claude/extra-1', 'shared/extra-2', 'claude/extra-3'].map(id => `select:${id}`),
    )
    expect(await labelOf(ui, 'select:shared/dup')).toBe('☐')
    expect((await propsOf(ui, 'select:shared/dup'))?.plain).toBe(true)
    expect((await propsOf(ui, 'card:shared/dup'))?.borderColor).toBe(isDesktop(surface) ? 'inactive' : undefined)
    expect(await ui.find({ key: 'selection-bar:install' })).toBeUndefined()

    await ui.press({ key: 'select:shared/dup' })
    expect(await labelOf(ui, 'select:shared/dup')).toBe('☑')
    expect((await propsOf(ui, 'card:shared/dup'))?.borderColor).toBe('claude')
    expect((await propsOf(ui, 'card:shared/extra-0'))?.borderColor).toBe(isDesktop(surface) ? 'inactive' : undefined)

    await ui.press({ key: 'select:shared/dup' })
    expect(await labelOf(ui, 'select:shared/dup')).toBe('☐')
    expect((await propsOf(ui, 'card:shared/dup'))?.borderColor).toBe(isDesktop(surface) ? 'inactive' : undefined)

    // the Installed view's cards have one too, tool-managed ones included
    await ui.press({ key: 'view-installed' })
    expect(await selects(ui)).toHaveLength(5)
    expect(await labelOf(ui, 'select:claude/learned')).toBe('☐')
    await ui.unmount()
  })

  test(`${surface}: the Install bar says how many are ticked and offers Install N, Select all shown and Clear`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, INSTALL, 'install')

    await tick(ui, 'shared/dup', 'claude/extra-1')
    expect(await textCount(ui, /^2 selected$/)).toBe(1)
    expect(await labelOf(ui, 'bulk-install')).toBe('Install 2')
    expect((await propsOf(ui, 'bulk-install'))?.variant).toBe('primary')
    expect(await labelOf(ui, 'select-all:install')).toBe('Select all shown (13)')
    expect(await labelOf(ui, 'clear-selection:install')).toBe('Clear')
    expect((await propsOf(ui, 'selection-bar:install'))?.borderColor).toBe('claude')
    // directly above the list: after the filters, before the first card
    const order = (await buttonKeys(ui)).concat()
    expect(order.indexOf('install-scope:all')).toBeLessThan(order.indexOf('bulk-install'))
    expect(order.indexOf('bulk-install')).toBeLessThan(order.indexOf('select:shared/dup'))

    await ui.press({ key: 'clear-selection:install' })
    expect(await ui.find({ key: 'selection-bar:install' })).toBeUndefined()
    expect(await ticked(ui)).toEqual([])
    await ui.unmount()
  })

  test(`${surface}: Select all shown ticks every filtered row across pages; filters keep the selection`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, INSTALL, 'install')

    await tick(ui, 'shared/dup', 'claude/extra-1')
    await ui.press({ key: 'install-scope:claude' })
    expect(await textCount(ui, /^2 selected$/)).toBe(1)
    expect(await labelOf(ui, 'select-all:install')).toBe('Select all shown (6)')

    // the six claude skills across two pages, one of them already ticked; dup stays ticked off screen
    await selectAll(ui, 'install')
    expect(await textCount(ui, /^7 selected$/)).toBe(1)
    expect(await ticked(ui)).toEqual(['claude/extra-1', 'claude/extra-3', 'claude/extra-5', 'claude/extra-7', 'claude/extra-9'].map(id => `select:${id}`))
    await ui.press({ key: 'next:install' })
    expect(await ticked(ui)).toEqual(['select:claude/extra-11'])

    await ui.press({ key: 'install-scope:all' })
    expect(await textCount(ui, /^7 selected$/)).toBe(1)
    await selectAll(ui, 'install')
    expect(await textCount(ui, /^13 selected$/)).toBe(1)
    expect(await labelOf(ui, 'bulk-install')).toBe('Install 13')
    for (const page of [0, 1, 2]) {
      const cards = await selects(ui)
      expect(await ticked(ui)).toEqual(cards)
      if (page < 2) await ui.press({ key: 'next:install' })
    }
    await ui.unmount()
  })

  test(`${surface}: Install N runs one call per scope with every ticked name, then clears the selection`, AT_REPO, async ($, on) => {
    const { w, ui, after } = await openTo($, on, surface, INSTALL, 'install')
    await tick(ui, 'claude/extra-1', 'shared/extra-0', 'shared/dup')

    const from = w.calls.length
    await ui.press({ key: 'bulk-install' })
    expect(after(from).slice(0, 2)).toEqual([
      'install dup extra-0 --scope shared --yes',
      'install extra-1 --scope claude --yes',
    ])
    expect(await ui.find({ key: 'selection-bar:install' })).toBeUndefined()
    expect(await ticked(ui)).toEqual([])
    expect(await textCount(ui, /^Installed 3 skills\.$/)).toBe(1)
    expect(w.toasts).toContain('Installed 3 skills.')
    await ui.unmount()
  })

  test(`${surface}: a rescan drops ticked skills that no longer exist`, AT_REPO, async ($, on) => {
    const { w, ui } = await openTo($, on, surface, INSTALL, 'install')
    await tick(ui, 'shared/dup', 'claude/extra-1')
    expect(await textCount(ui, /^2 selected$/)).toBe(1)

    // dup was installed behind the pane's back
    w.answer('status --json', json(MISSING.map(row => (row.name === 'dup' ? { ...row, state: 'installed' } : row))))
    await ui.press({ key: 'refresh' })
    expect(await textCount(ui, /^1 selected$/)).toBe(1)
    expect(await ticked(ui)).toEqual(['select:claude/extra-1'])
    await ui.unmount()
  })

  test(`${surface}: the Installed bar counts what each button applies to: Update, Relink, Retire…`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, INSTALLED, 'installed')

    // alpha is clean: only Retire applies
    await tick(ui, 'shared/alpha')
    expect(await textCount(ui, /^1 selected$/)).toBe(1)
    expect(await labelOf(ui, 'bulk-retire')).toBe('Retire 1…')
    expect(await ui.find({ key: 'bulk-update' })).toBeUndefined()
    expect(await ui.find({ key: 'bulk-relink' })).toBeUndefined()

    // beta is modified with a broken link; ghost is foreign; learned is tool-managed (nothing applies)
    await tick(ui, 'shared/beta', 'claude/ghost', 'claude/learned')
    expect(await textCount(ui, /^4 selected$/)).toBe(1)
    expect(await labelOf(ui, 'bulk-update')).toBe('Update 1')
    expect(await labelOf(ui, 'bulk-relink')).toBe('Relink 1')
    expect(await labelOf(ui, 'bulk-retire')).toBe('Retire 3…')
    expect((await propsOf(ui, 'bulk-update'))?.variant).toBe('primary')
    expect(await labelOf(ui, 'select-all:installed')).toBe('Select all shown (13)')
    expect(await labelOf(ui, 'clear-selection:installed')).toBe('Clear')

    // the bar follows the card filters without losing anything
    await ui.press({ key: 'installed-filter:modified' })
    expect(await textCount(ui, /^4 selected$/)).toBe(1)
    expect(await labelOf(ui, 'select-all:installed')).toBe('Select all shown (1)')
    await ui.unmount()
  })

  test(`${surface}: Update N and Relink N run on the ticked skills they apply to`, AT_REPO, async ($, on) => {
    const { w, ui, after } = await openTo($, on, surface, INSTALLED, 'installed')
    await tick(ui, 'shared/alpha', 'shared/beta')

    const from = w.calls.length
    await ui.press({ key: 'bulk-update' })
    expect(after(from).filter(command => command.startsWith('update '))).toEqual(['update beta --scope shared --yes'])
    expect(await textCount(ui, /^Updated 1 skill\.$/)).toBe(1)
    expect(await ticked(ui)).toEqual([])

    await tick(ui, 'shared/beta', 'shared/alpha')
    await ui.press({ key: 'bulk-relink' })
    expect(after(from).filter(command => command.startsWith('relink '))).toEqual(['relink beta --yes'])
    await ui.unmount()
  })

  test(`${surface}: Retire N asks in the bar's place, lists the names, then runs one call per scope in order`, AT_REPO, async ($, on) => {
    const { w, ui, after } = await openTo($, on, surface, INSTALLED, 'installed')
    // the bar (and its Select all) appears with the first tick
    await tick(ui, 'shared/alpha')
    await selectAll(ui, 'installed')
    expect(await textCount(ui, /^13 selected$/)).toBe(1)
    expect(await labelOf(ui, 'bulk-retire')).toBe('Retire 12…')

    const from = w.calls.length
    await ui.press({ key: 'bulk-retire' })
    expect(after(from)).toEqual([])
    // the confirm card is where the bar was: the bar's buttons are gone, the card names the first eight
    expect(await ui.find({ key: 'selection-bar:installed' })).toBeUndefined()
    expect((await propsOf(ui, 'confirm'))?.borderColor).toBe('warning')
    expect(await textCount(ui, /^Retire 12 skills\?$/)).toBe(1)
    const said = (await textsUnder(ui, 'confirm')).join(' ')
    expect(said).toContain(
      'shared/alpha, shared/beta, claude/gamma, claude/ghost, shared/have-0, claude/have-1, shared/have-2, claude/have-3 and 4 more',
    )
    expect(await labelOf(ui, 'confirm-yes')).toBe('Yes, retire 12')

    // the bar's buttons are gone; the other presses are ignored while it is up: the tick boxes do not move
    expect(await ui.find({ key: 'clear-selection:installed' })).toBeUndefined()
    await ui.press({ key: 'select:claude/gamma' })
    expect(await ticked(ui)).toHaveLength(5)
    expect(after(from)).toEqual([])

    await ui.press({ key: 'confirm-no' })
    expect(await textCount(ui, /^13 selected$/)).toBe(1)
    expect(after(from)).toEqual([])

    await ui.press({ key: 'bulk-retire' })
    await ui.press({ key: 'confirm-yes' })
    expect(after(from).slice(0, 2)).toEqual([RETIRE_SHARED, RETIRE_CLAUDE])
    expect(after(from).filter(command => command.startsWith('retire '))).toHaveLength(2)
    expect(await ui.find({ key: 'selection-bar:installed' })).toBeUndefined()
    expect(await ui.find({ key: 'confirm' })).toBeUndefined()
    expect(await ticked(ui)).toEqual([])
    expect(await textCount(ui, /^Retired 12 skills \(moved to a backup\)\.$/)).toBe(1)
    await ui.unmount()
  })

  test(`${surface}: a failing first call stops the second and keeps everything ticked`, AT_REPO, async ($, on) => {
    const canned = { ...INSTALLED.canned, [RETIRE_SHARED]: bad('error: boom') }
    const { w, ui, after } = await openTo($, on, surface, { canned }, 'installed')
    await tick(ui, 'shared/alpha')
    await selectAll(ui, 'installed')

    const from = w.calls.length
    await ui.press({ key: 'bulk-retire' })
    await ui.press({ key: 'confirm-yes' })
    expect(after(from).filter(command => command.startsWith('retire '))).toEqual([RETIRE_SHARED])
    expect((await propsOf(ui, 'callout:Something went wrong'))?.borderColor).toBe('error')
    expect(await textCount(ui, /^Retire 12 skills failed: error: boom \(0 of 12 done\)$/)).toBe(1)
    expect(await textCount(ui, /^13 selected$/)).toBe(1)
    await ui.unmount()
  })

  test(`${surface}: a failure on a later scope says how many were done and leaves only the rest ticked`, AT_REPO, async ($, on) => {
    const canned = { ...INSTALLED.canned, [RETIRE_CLAUDE]: bad('error: boom') }
    const { w, ui, after } = await openTo($, on, surface, { canned }, 'installed')
    await tick(ui, 'shared/alpha')
    await selectAll(ui, 'installed')

    const from = w.calls.length
    await ui.press({ key: 'bulk-retire' })
    await ui.press({ key: 'confirm-yes' })
    expect(after(from).filter(command => command.startsWith('retire '))).toEqual([RETIRE_SHARED, RETIRE_CLAUDE])
    expect(await textCount(ui, /^Retire 12 skills failed: error: boom \(6 of 12 done\)$/)).toBe(1)
    // the six shared skills left the selection; the claude ones (and the tool-managed one) are still ticked
    expect(await textCount(ui, /^7 selected$/)).toBe(1)
    expect((await ticked(ui)).every(key => key?.startsWith('select:claude/'))).toBe(true)
    await ui.unmount()
  })
}
