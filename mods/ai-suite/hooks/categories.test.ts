// Run with: claude plugin test mods/ai-suite
// The category filter of the Install and Installed views on both surfaces: a Category Select
// beside the filter chips (under them in a narrow pane), its options, filtering with the pager
// back on page 1, the empty state, the category on each card's title row, and the pure helpers.
import { expect, test } from 'claude-code/testing'
import { parseStatus } from './parse'
import { ALL_CATEGORIES, CATEGORY_ORDER, categoryOptions } from './presets'
import { categoriesOf, filterInstalled, filterMissing } from './summary'
import {
  AT_REPO,
  PANE,
  SURFACES,
  allText,
  badgeText,
  buttonKeys,
  isActive,
  isDesktop,
  json,
  labelOf,
  mountPane,
  openTo,
  run,
  skill,
  textCount,
  world,
} from './testkit'

type Choice = { value: string; label?: string }

const row = (scope: string, name: string, state: string, category?: string) =>
  skill(scope, name, state, category === undefined ? {} : { category })

/** Nine skills on disk and ten missing; the last missing one (and one on disk) comes with no category field. */
const ROWS = [
  ...Array.from({ length: 6 }, (_, at) => row('shared', `orch-${at}`, 'installed', 'Orchestration')),
  row('claude', 'inst-ui', 'installed', 'Design & UX'),
  row('claude', 'inst-plain', 'installed'),
  row('claude', 'mod-web', 'modified', 'Web, API & data'),
  ...Array.from({ length: 7 }, (_, at) => row('shared', `web-${at}`, 'not-installed', 'Web, API & data')),
  row('shared', 'ui-0', 'not-installed', 'Design & UX'),
  row('claude', 'ui-1', 'not-installed', 'Design & UX'),
  row('shared', 'plain-0', 'not-installed'),
]
const WITH_ROWS = { canned: { 'status --json': json(ROWS) } }

const choices = async (ui: Awaited<ReturnType<typeof openTo>>['ui'], key: string) =>
  ((await ui.find({ key }))?.props.options as Choice[] | undefined) ?? []
const valueOf = async (ui: Awaited<ReturnType<typeof openTo>>['ui'], key: string) => (await ui.find({ key }))?.props.value
const installKeys = async (ui: Awaited<ReturnType<typeof openTo>>['ui']) =>
  (await buttonKeys(ui)).filter(key => key.startsWith('install:'))
const cardKeys = async (ui: Awaited<ReturnType<typeof openTo>>['ui']) =>
  (await ui.findAll({ type: 'Box' })).map(box => box.key ?? '').filter(key => key.startsWith('card:'))

for (const surface of SURFACES) {
  test(`${surface}: Install has a Category Select beside the chips: All categories, then the present ones in canonical order`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, WITH_ROWS, 'install')

    const select = await ui.find({ key: 'category:install' })
    expect(select?.props.label).toBe('Category')
    expect(select?.props.value).toBe('all')
    // the order is the canonical one (Web before Design), not the order the rows came in; no category is Other, last
    const options = await choices(ui, 'category:install')
    expect(options.map(option => option.value)).toEqual(['all', 'Web, API & data', 'Design & UX', 'Other'])
    expect(options[0]?.label).toBe('All categories')
    expect(options.slice(1).every(option => option.label === undefined)).toBe(true)
    expect(CATEGORY_ORDER.indexOf('Web, API & data')).toBeLessThan(CATEGORY_ORDER.indexOf('Design & UX'))

    // on the chips' own row: the chips and the Select share one row box, the chips still work
    expect((await ui.find({ key: 'filters:install' }))?.props.flexDirection).toBe('row')
    expect(await isActive(ui, 'All')).toBe(true)
    expect(await labelOf(ui, 'install-scope:claude')).toBe('Claude')
    await ui.unmount()
  })

  test(`${surface}: picking a category filters the Install cards, goes back to page 1 and narrows Install all`, AT_REPO, async ($, on) => {
    const { w, ui, after } = await openTo($, on, surface, WITH_ROWS, 'install')

    expect(await textCount(ui, /^Showing 1-5 of 10$/)).toBe(1)
    await ui.press({ key: 'next:install' })
    expect(await textCount(ui, /^Showing 6-10 of 10$/)).toBe(1)

    await ui.select({ key: 'category:install', value: 'Web, API & data' })
    expect(await valueOf(ui, 'category:install')).toBe('Web, API & data')
    expect(await textCount(ui, /^Showing 1-5 of 7$/)).toBe(1)
    expect(await installKeys(ui)).toEqual([0, 1, 2, 3, 4].map(at => `install:shared/web-${at}`))
    expect(await labelOf(ui, 'install-all')).toBe('Install all 7')
    await ui.press({ key: 'next:install' })
    expect(await installKeys(ui)).toEqual(['install:shared/web-5', 'install:shared/web-6'])
    await ui.press({ key: 'prev:install' })

    // Install all names what is shown and nothing else
    const from = w.calls.length
    await ui.press({ key: 'install-all' })
    expect(await textCount(ui, /^Install 7 missing skills\?$/)).toBe(1)
    await ui.press({ key: 'confirm-yes' })
    expect(after(from)[0]).toBe(`install ${[0, 1, 2, 3, 4, 5, 6].map(at => `web-${at}`).join(' ')} --scope shared --yes`)

    // it combines with the scope chips; All categories lifts it
    await ui.select({ key: 'category:install', value: 'Design & UX' })
    expect(await installKeys(ui)).toEqual(['install:shared/ui-0', 'install:claude/ui-1'])
    await ui.press({ key: 'install-scope:claude' })
    expect(await installKeys(ui)).toEqual(['install:claude/ui-1'])
    await ui.select({ key: 'category:install', value: 'all' })
    expect(await installKeys(ui)).toEqual(['install:claude/ui-1'])
    await ui.press({ key: 'install-scope:all' })
    expect(await textCount(ui, /^Showing 1-5 of 10$/)).toBe(1)
    await ui.unmount()
  })

  test(`${surface}: a skill with no category field is Other, and its card says so`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, WITH_ROWS, 'install')

    await ui.select({ key: 'category:install', value: 'Other' })
    expect(await installKeys(ui)).toEqual(['install:shared/plain-0'])
    expect(await cardKeys(ui)).toEqual(['card:shared/plain-0'])
    expect(await textCount(ui, /^· Other$/)).toBe(1)
    await ui.unmount()
  })

  test(`${surface}: the card title row holds the name, the scope, then the category dim`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, WITH_ROWS, 'install')
    await ui.press({ key: 'next:install' })

    const texts = await allText(ui)
    const at = texts.indexOf('ui-0')
    const scope = isDesktop(surface) ? 'shared' : '[shared]'
    expect(texts.slice(at, at + 4)).toEqual(['ui-0', scope, '· Design & UX', badgeText(surface, '· missing')])
    expect((await ui.find({ type: 'Text', text: /^· Design & UX$/ }))?.props.dimColor).toBe(true)
    expect(await textCount(ui, /^· Design & UX$/)).toBe(2)
    expect(await textCount(ui, /^· Web, API & data$/)).toBe(2)

    // on the Installed cards too
    await ui.press({ key: 'view-installed' })
    expect(await textCount(ui, /^· Orchestration$/)).toBe(5)
    await ui.unmount()
  })

  test(`${surface}: the Updates cards show the category of a skill the machine knows`, AT_REPO, async ($, on) => {
    const changed = [{ scope: 'shared', name: 'orch-0', files: ['SKILL.md'] }, { scope: 'shared', name: 'unknown', files: ['SKILL.md'] }]
    const canned = { ...WITH_ROWS.canned, 'updates --json': json({ git: {}, commits: [], changed }) }
    const { ui } = await openTo($, on, surface, { canned }, 'updates')

    expect(await textCount(ui, /^· Orchestration$/)).toBe(1)
    expect((await cardKeys(ui)).filter(key => key.startsWith('card:shared/'))).toEqual(['card:shared/orch-0', 'card:shared/unknown'])
    // the unknown skill has no row to take a category from (the terminal's `· not on this machine` badge starts lower case)
    expect(await textCount(ui, /^· [A-Z]/)).toBe(1)
    await ui.unmount()
  })

  test(`${surface}: with nothing in the category the Install view says so and offers all categories`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, WITH_ROWS, 'install')

    // the claude scope holds one Design & UX skill: a Web pick over it shows nothing
    await ui.select({ key: 'category:install', value: 'Web, API & data' })
    await ui.press({ key: 'install-scope:claude' })
    expect(await installKeys(ui)).toEqual([])
    expect(await textCount(ui, /^No skill in Web, API & data matches\.$/)).toBe(1)
    expect(await textCount(ui, /^No missing skill matches this filter\.$/)).toBe(0)
    expect(await labelOf(ui, 'install-show-all-categories')).toBe('Show all categories')
    expect(await ui.find({ key: 'install-all' })).toBeUndefined()

    await ui.press({ key: 'install-show-all-categories' })
    expect(await valueOf(ui, 'category:install')).toBe('all')
    expect(await installKeys(ui)).toEqual(['install:claude/ui-1'])
    expect(await textCount(ui, /^No skill in /)).toBe(0)

    // when lifting the category would show nothing either, the generic sentence stays
    await ui.select({ key: 'category:install', value: 'Design & UX' })
    await ui.input({ key: 'install-query', text: 'zzz', kind: 'change' })
    expect(await textCount(ui, /^No missing skill matches this filter\.$/)).toBe(1)
    expect(await textCount(ui, /^No skill in /)).toBe(0)
    await ui.unmount()
  })

  test(`${surface}: Installed has the same Select over the skills on disk; a pick filters, resets the page, and an empty category is named`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, WITH_ROWS, 'installed')

    const select = await ui.find({ key: 'category:installed' })
    expect(select?.props).toMatchObject({ label: 'Category', value: 'all' })
    // only what is on disk counts: no missing skill adds a category (the missing web ones share one already)
    expect((await choices(ui, 'category:installed')).map(option => option.value)).toEqual([
      'all',
      'Orchestration',
      'Web, API & data',
      'Design & UX',
      'Other',
    ])
    expect((await ui.find({ key: 'filters:installed' }))?.props.flexDirection).toBe('row')
    expect(await textCount(ui, /^Showing 1-5 of 9$/)).toBe(1)
    await ui.press({ key: 'next:installed' })
    expect(await textCount(ui, /^Showing 6-9 of 9$/)).toBe(1)

    await ui.select({ key: 'category:installed', value: 'Orchestration' })
    expect(await textCount(ui, /^Showing 1-5 of 6$/)).toBe(1)
    expect((await cardKeys(ui)).every(key => key.startsWith('card:shared/orch-'))).toBe(true)
    await ui.select({ key: 'category:installed', value: 'Design & UX' })
    expect(await cardKeys(ui)).toEqual(['card:claude/inst-ui'])

    // the chips narrow within the category; a Modified chip finds none in Design & UX
    await ui.press({ key: 'installed-filter:modified' })
    expect(await cardKeys(ui)).toEqual([])
    expect(await textCount(ui, /^No skill in Design & UX matches\.$/)).toBe(1)
    await ui.press({ key: 'installed-show-all-categories' })
    expect(await valueOf(ui, 'category:installed')).toBe('all')
    expect(await cardKeys(ui)).toEqual(['card:claude/mod-web'])

    // nothing matches even with every category (no skill has a problem): the generic sentence
    await ui.select({ key: 'category:installed', value: 'Orchestration' })
    await ui.press({ key: 'installed-filter:problems' })
    expect(await textCount(ui, /^No skill matches this filter\.$/)).toBe(1)
    expect(await textCount(ui, /^No skill in /)).toBe(0)
    await ui.unmount()
  })

  test(`${surface}: jumping to Installed from Overview lifts a category pick so the count matches`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, WITH_ROWS, 'installed')

    await ui.select({ key: 'category:installed', value: 'Orchestration' })
    await ui.press({ key: 'view-overview' })
    await ui.press({ key: 'attention-modified' })
    expect(await isActive(ui, 'Installed')).toBe(true)
    expect(await valueOf(ui, 'category:installed')).toBe('all')
    expect(await cardKeys(ui)).toEqual(['card:claude/mod-web'])
    await ui.unmount()
  })

  test(`${surface}: Overview's Install missing still installs every missing skill whatever the Install view was set to`, AT_REPO, async ($, on) => {
    const { w, ui, after } = await openTo($, on, surface, WITH_ROWS, 'install')
    await ui.select({ key: 'category:install', value: 'Design & UX' })
    await ui.press({ key: 'view-overview' })

    const from = w.calls.length
    expect(await labelOf(ui, 'overview-install')).toBe('Install 10 missing')
    await ui.press({ key: 'overview-install' })
    expect(await textCount(ui, /^Install 10 missing skills\?$/)).toBe(1)
    await ui.press({ key: 'confirm-yes' })
    expect(after(from).filter(command => command.startsWith('install '))).toHaveLength(2)
    await ui.unmount()
  })

  test(`${surface}: in a narrow pane the Select goes under the chips and no line is wider than the pane`, AT_REPO, async ($, on) => {
    world(on, WITH_ROWS)
    await $.command.run(run('skills'))
    const ui = await mountPane($, surface, { ...PANE, bodyColumns: 40 })

    for (const view of ['install', 'installed']) {
      await ui.press({ key: `view-${view}` })
      expect((await ui.find({ key: `filters:${view}` }))?.props.flexDirection).toBe('column')
      expect((await ui.find({ key: `category:${view}` }))?.props.label).toBe('Category')
      expect(Math.max(...(await allText(ui)).map(line => line.length))).toBeLessThanOrEqual(40)
    }
    await ui.unmount()
  })

  test(`${surface}: with no row holding a category the Select is not drawn`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, { canned: { 'status --json': json([]) } }, 'install')
    expect(await ui.find({ key: 'category:install' })).toBeUndefined()
    await ui.press({ key: 'view-installed' })
    expect(await ui.find({ key: 'category:installed' })).toBeUndefined()
    await ui.unmount()
  })
}

// --------------------------------------------------------------- pure helpers

test('category options: All categories first, the present ones in canonical order, a new name before Other, the current pick kept', () => {
  const values = (present: string[], current = ALL_CATEGORIES) => categoryOptions(present, current).map(option => option.value)
  expect(categoryOptions([], ALL_CATEGORIES)).toEqual([{ value: 'all', label: 'All categories' }])
  expect(values(['Other', 'Design & UX', 'Orchestration', 'Design & UX'])).toEqual(['all', 'Orchestration', 'Design & UX', 'Other'])
  expect(values(['Other', 'Zebra', 'Alpaca', 'Presentations'])).toEqual(['all', 'Presentations', 'Alpaca', 'Zebra', 'Other'])
  // a pick no row holds any more stays in the list, in its place
  expect(values(['Orchestration'], 'Web, API & data')).toEqual(['all', 'Orchestration', 'Web, API & data'])
  expect(CATEGORY_ORDER[0]).toBe('Orchestration')
  expect(CATEGORY_ORDER.at(-1)).toBe('Other')
  expect(new Set(CATEGORY_ORDER).size).toBe(CATEGORY_ORDER.length)
})

test('parseStatus reads category, treats a missing, empty or non-text one as Other, and the filters honour it', () => {
  const rows = parseStatus([
    row('shared', 'a', 'not-installed', 'Design & UX'),
    row('shared', 'b', 'not-installed'),
    row('claude', 'c', 'not-installed', '  '),
    { ...row('claude', 'd', 'installed'), category: 7 },
    row('claude', 'e', 'installed', ' Web, API & data '),
  ])
  expect(rows?.map(each => each.category)).toEqual(['Design & UX', 'Other', 'Other', 'Other', 'Web, API & data'])
  const all = rows ?? []
  const none = { installScope: 'all', installQuery: '' } as const
  expect(filterMissing(all, { ...none, installCategory: 'all' }).map(each => each.name)).toEqual(['a', 'b', 'c'])
  expect(filterMissing(all, { ...none, installCategory: 'Other' }).map(each => each.name)).toEqual(['b', 'c'])
  expect(filterMissing(all, { installScope: 'claude', installQuery: '', installCategory: 'Other' }).map(each => each.name)).toEqual(['c'])
  expect(filterInstalled(all, 'all', 'Other').map(each => each.name)).toEqual(['d'])
  expect(filterInstalled(all, 'all').map(each => each.name)).toEqual(['d', 'e'])
  expect(categoriesOf(all)).toEqual(['Design & UX', 'Other', 'Web, API & data'])
})
