// Run with: claude plugin test mods/ai-suite
// Where things are drawn, on both surfaces: a confirm card right under the card or button row
// that asked for it, the last action as one dim line in the header (an error as a callout below
// it, before the filters), the Tag Select sharing the chip row or stacking under it, and the
// blank rows between blocks. What a press does is in views.test.ts, manage.test.ts and selection.test.ts.
import { expect, test } from 'claude-code/testing'
import { trimMessage } from './cli'
import { namesLine } from './selection'
import {
  AT_REPO,
  PANE,
  STATUS,
  SURFACES,
  allText,
  bad,
  isDesktop,
  json,
  keyedOrder,
  mountPane,
  openTo,
  propsOf,
  run,
  siblingKeys,
  skill,
  text,
  textCount,
  textsUnder,
  world,
} from './testkit'
import type { WorldOptions } from './testkit'

const MANY = [...STATUS, ...Array.from({ length: 12 }, (_, at) => skill('shared', `extra-${at}`, 'not-installed'))]
const WITH_MANY: WorldOptions = { canned: { 'status --json': json(MANY) } }

/** A few missing skills that carry tags, so the Tag Select is drawn. */
const TAGGED = [
  skill('shared', 'web-0', 'not-installed', { tags: ['backend', 'api'] }),
  skill('claude', 'ui-0', 'not-installed', { tags: ['design', 'frontend'] }),
  skill('shared', 'plain-0', 'not-installed'),
  skill('claude', 'inst', 'installed', { tags: ['design'] }),
]
const WITH_TAGS: WorldOptions = { canned: { 'status --json': json(TAGGED) } }

/** The first `count` keys from `key` on in the drawing's document order. */
const from = (order: readonly string[], key: string, count: number): string[] =>
  order.slice(order.indexOf(key), order.indexOf(key) + count)

const NOTES = text('Plan (1 step(s)):\nshared/dup: linked into claude and codex\nshared/dup: description rewritten\nDone.\n')

for (const surface of SURFACES) {
  test(`${surface}: a pending Retire draws its confirm card as the next sibling of the card, below the filters`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, {}, 'installed')

    await ui.press({ key: 'retire:claude/ghost' })
    const siblings = await siblingKeys(ui, 'card:claude/ghost')
    expect(siblings.slice(siblings.indexOf('card:claude/ghost'), siblings.indexOf('card:claude/ghost') + 3)).toEqual([
      'card:claude/ghost',
      'confirm',
      'card:claude/learned',
    ])
    const order = await keyedOrder(ui)
    expect(order.indexOf('filter-area')).toBeLessThan(order.indexOf('card:claude/ghost'))
    // the card's own buttons (Retire, Files) come first, and then the confirm card
    expect(order.slice(order.indexOf('card:claude/ghost'), order.indexOf('card:claude/ghost') + 4)).toEqual([
      'card:claude/ghost',
      'select:claude/ghost',
      'retire:claude/ghost',
      'files:claude/ghost',
    ])
    expect(order[order.indexOf('files:claude/ghost') + 1]).toBe('confirm')
    // the other buttons stay drawn, dim, and a press on them is ignored
    expect((await propsOf(ui, 'select:shared/alpha'))?.dimColor).toBe(true)
    await ui.press({ key: 'select:shared/alpha' })
    await ui.press({ key: 'view-updates' })
    expect(await textCount(ui, /^Retire claude\/ghost\?$/)).toBe(1)
    expect((await keyedOrder(ui)).includes('selection-bar:installed')).toBe(false)

    await ui.press({ key: 'confirm-no' })
    expect(await ui.find({ key: 'confirm' })).toBeUndefined()
    // another card's Retire moves the card under that one
    await ui.press({ key: 'retire:shared/alpha' })
    const again = await siblingKeys(ui, 'card:shared/alpha')
    expect(again[again.indexOf('card:shared/alpha') + 1]).toBe('confirm')
    expect(again.filter(key => key === 'confirm')).toHaveLength(1)
    await ui.unmount()
  })

  test(`${surface}: Overview, Updates, Install and Settings draw it right under the button row that asked`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, WITH_MANY)

    // Overview: after the whole row of view-level buttons
    await ui.press({ key: 'overview-install' })
    let order = await keyedOrder(ui)
    expect(from(order, 'overview-install', 4)).toEqual(['overview-install', 'overview-fetch', 'refresh', 'confirm'])
    await ui.press({ key: 'confirm-no' })

    // Install: inside the footer card, under its buttons
    await ui.press({ key: 'view-install' })
    await ui.press({ key: 'install-all' })
    order = await keyedOrder(ui)
    expect(from(order, 'install-all', 3)).toEqual(['install-all', 'refresh', 'confirm'])
    await ui.press({ key: 'confirm-no' })

    // Updates: Pull under the git card's buttons; Update changed under its own row
    await ui.press({ key: 'view-updates' })
    await ui.press({ key: 'pull' })
    order = await keyedOrder(ui)
    expect(from(order, 'pull', 3)).toEqual(['pull', 'confirm', 'confirm-yes'])
    expect(order[order.indexOf('confirm-no') + 1]).toBe('commits')
    await ui.press({ key: 'confirm-no' })
    await ui.press({ key: 'update-changed' })
    order = await keyedOrder(ui)
    expect(from(order, 'update-changed', 2)).toEqual(['update-changed', 'confirm'])
    expect(order[order.indexOf('confirm-no') + 1]).toBe('refresh')
    await ui.press({ key: 'confirm-no' })

    // Settings: Apply under its button, a Reset pick under the Reset control
    await ui.press({ key: 'view-settings' })
    await ui.press({ key: 'apply' })
    let kids = await siblingKeys(ui, 'confirm')
    expect(kids.indexOf('confirm')).toBeLessThan(kids.length - 1)
    await ui.press({ key: 'confirm-no' })
    await ui.select({ key: 'reset-setting', value: 'tools.claude' })
    kids = await siblingKeys(ui, 'confirm')
    expect(kids.at(-1)).toBe('confirm')
    expect(await textCount(ui, /^Reset Claude Code to its default\?$/)).toBe(1)
    await ui.unmount()
  })

  test(`${surface}: a Workflows Retire or Push confirm sits under its workflow card`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, {}, 'workflows')

    await ui.press({ key: 'workflow-push:ship' })
    let kids = await siblingKeys(ui, 'workflow:ship')
    expect(kids.slice(kids.indexOf('workflow:ship'), kids.indexOf('workflow:ship') + 3)).toEqual(['workflow:ship', 'confirm', 'workflow:broken'])
    await ui.press({ key: 'confirm-no' })
    await ui.press({ key: 'workflow-retire:broken' })
    kids = await siblingKeys(ui, 'workflow:broken')
    expect(kids[kids.indexOf('workflow:broken') + 1]).toBe('confirm')
    await ui.unmount()
  })

  test(`${surface}: the last action is one dim line in the header; a failure is a callout below it, before the filters`, AT_REPO, async ($, on) => {
    const canned = {
      ...WITH_MANY.canned,
      'install dup --scope shared --yes': NOTES,
      'install extra-0 --scope shared --yes': bad('error: unknown skill: extra-0'),
    }
    const { ui } = await openTo($, on, surface, { canned }, 'install')

    await ui.press({ key: 'install:shared/dup' })
    const line = 'Installed shared/dup. · shared/dup: linked into claude and codex'
    const shown = (await textsUnder(ui, 'header')).filter(each => each.startsWith('Installed'))
    expect(shown).toHaveLength(1)
    expect(shown[0]?.startsWith('Installed shared/dup.')).toBe(true)
    expect(line.startsWith(shown[0]?.split(' · ')[0] ?? '?')).toBe(true)
    expect((await ui.find({ type: 'Text', text: /^Installed shared\/dup\./ }))?.props.dimColor).toBe(true)
    expect(await ui.find({ key: 'errors' })).toBeUndefined()
    expect(await textCount(ui, /^Installed shared\/dup\./)).toBe(1)
    // the header ends with the line; the filters come after the header, separated by the root's gap or margin
    expect((await siblingKeys(ui, 'header')).slice(0, 2)).toEqual(['header', ''])
    expect((await keyedOrder(ui)).indexOf('header')).toBeLessThan((await keyedOrder(ui)).indexOf('filter-area'))

    await ui.press({ key: 'install:shared/extra-0' })
    expect(await siblingKeys(ui, 'header')).toEqual(['header', 'errors', ''])
    const order = await keyedOrder(ui)
    expect(order.indexOf('header')).toBeLessThan(order.indexOf('errors'))
    expect(order.indexOf('errors')).toBeLessThan(order.indexOf('filter-area'))
    expect((await propsOf(ui, 'errors'))?.marginBottom).toBe(isDesktop(surface) ? 1 : undefined)
    expect((await propsOf(ui, 'callout:Something went wrong'))?.borderColor).toBe('error')
    // no last-action line while the failure is up
    expect(await textsUnder(ui, 'header')).not.toContain('Installed shared/dup.')
    await ui.unmount()
  })

  test(`${surface}: in a narrow pane the line keeps the whole sentence and never ends in "· …"`, AT_REPO, async ($, on) => {
    const canned = { ...WITH_MANY.canned, 'install dup --scope shared --yes': NOTES }
    world(on, { canned })
    await $.command.run(run('skills'))
    const ui = await mountPane($, surface, { ...PANE, bodyColumns: 40 })
    await ui.press({ key: 'view-install' })
    await ui.press({ key: 'install:shared/dup' })

    const header = await textsUnder(ui, 'header')
    expect(header).toContain('Installed shared/dup.')
    expect(header.some(each => each.includes('linked into'))).toBe(false)
    expect((await allText(ui)).some(each => /·\s*…$/.test(each))).toBe(false)
    expect(Math.max(...(await allText(ui)).map(each => each.length))).toBeLessThanOrEqual(40)
    await ui.unmount()
  })

  test(`${surface}: the Tag Select shares the chip row when it fits and stacks under it when it does not`, AT_REPO, async ($, on) => {
    world(on, WITH_TAGS)
    await $.command.run(run('skills'))
    const desk = isDesktop(surface)

    for (const view of ['install', 'installed']) {
      const wide = await mountPane($, surface, { ...PANE, bodyColumns: 100 })
      await wide.press({ key: `view-${view}` })
      const row = await propsOf(wide, `filters:${view}`)
      expect(row).toMatchObject({ flexDirection: 'row', justifyContent: 'space-between' })
      // chips on the left (the unkeyed row), the Select on the right
      expect(await siblingKeys(wide, `tag:${view}`)).toEqual(['', `tag:${view}`])
      await wide.unmount()

      const narrow = await mountPane($, surface, { ...PANE, bodyColumns: 40 })
      await narrow.press({ key: `view-${view}` })
      const stacked = await propsOf(narrow, `filters:${view}`)
      expect(stacked).toMatchObject({ flexDirection: 'column' })
      expect(stacked?.gap).toBe(desk ? 1 : undefined)
      await narrow.unmount()
    }

    // a pane that is wide in the terminal's cells but not on the desktop, where a chip is a padded button
    const middle = await mountPane($, surface, { ...PANE, bodyColumns: 60 })
    await middle.press({ key: 'view-install' })
    expect((await propsOf(middle, 'filters:install'))?.flexDirection).toBe(desk ? 'column' : 'row')
    await middle.unmount()
  })

  test(`${surface}: blank rows: the filter area, the pager and the view-level buttons are held off their neighbours`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, WITH_MANY, 'install')
    const desk = isDesktop(surface)

    const area = await propsOf(ui, 'filter-area')
    expect(area?.marginBottom).toBe(desk ? 1 : undefined)
    expect(area?.gap).toBe(desk ? 1 : undefined)
    expect((await propsOf(ui, 'pager:install'))?.marginTop).toBe(desk ? 1 : undefined)

    // the Refresh button's own Box carries the margin on the desktop
    await ui.press({ key: 'view-installed' })
    const holders = (await ui.findAll({ type: 'Box' })).filter(box =>
      ((box as { children?: { props?: { key?: string } }[] }).children ?? []).some(child => child.props?.key === 'refresh'),
    )
    expect(holders).toHaveLength(1)
    expect(holders[0]?.props.marginTop).toBe(desk ? 1 : undefined)
    await ui.unmount()
  })
}

test('trimMessage keeps the whole sentence and whole notes, and never leaves a dangling separator', () => {
  const full = 'Retired shared/x (moved to a backup). · shared/x: moved to ~/.agents/backups'
  expect(trimMessage(full, 100)).toBe(full)
  expect(trimMessage(full, 60)).toBe('Retired shared/x (moved to a backup).')
  expect(trimMessage(full, 38)).toBe('Retired shared/x (moved to a backup).')
  expect(trimMessage(full, 20)).toBe('Retired shared/x (m…')
  expect(trimMessage(full, 20).endsWith('· …')).toBe(false)
  expect(trimMessage('a   b · c', 20)).toBe('a b · c')
  expect(trimMessage('', 10)).toBe('')
})

test('namesLine lists the first eight keys and then says how many more', () => {
  const keys = Array.from({ length: 11 }, (_, at) => `shared/s-${at}`)
  expect(namesLine(keys.slice(0, 3))).toBe('shared/s-0, shared/s-1, shared/s-2')
  expect(namesLine(keys.slice(0, 8))).toBe(keys.slice(0, 8).join(', '))
  expect(namesLine(keys)).toBe(`${keys.slice(0, 8).join(', ')} and 3 more`)
  expect(namesLine([])).toBe('')
})
