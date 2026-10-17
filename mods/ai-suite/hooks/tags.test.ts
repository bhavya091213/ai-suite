// Run with: claude plugin test mods/ai-suite
// The tag filter of the Install and Installed views on both surfaces: a Tag Select beside the filter
// chips (under them in a narrow pane), its options with counts, filtering with the pager back on
// page 1, Install all scoped to the pick, skills without tags, the tags on each card's title row,
// and the empty state. The pure helpers are in tags_helpers.test.ts.
import { expect, test } from 'claude-code/testing'
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

const row = (scope: string, name: string, state: string, tags?: string[], category?: string) =>
  skill(scope, name, state, {
    ...(tags === undefined ? {} : { tags }),
    ...(category === undefined ? {} : { category }),
  })

const WEB = ['backend', 'api']

/**
 * Nine skills on disk and ten missing. Two missing skills carry a tag the mod does not know
 * (`aardvark`, `zebra`), one carries four tags (the card draws three), and one on disk and one
 * missing skill come with no `tags` field at all.
 */
const ROWS = [
  ...Array.from({ length: 6 }, (_, at) => row('shared', `orch-${at}`, 'installed', ['orchestration', 'workflows'], 'Orchestration')),
  row('claude', 'inst-ui', 'installed', ['design', 'frontend'], 'Design & UX'),
  row('claude', 'inst-plain', 'installed'),
  row('claude', 'mod-web', 'modified', WEB, 'Web, API & data'),
  row('shared', 'web-0', 'not-installed', [...WEB, 'zebra'], 'Web, API & data'),
  ...Array.from({ length: 6 }, (_, at) => row('shared', `web-${at + 1}`, 'not-installed', WEB, 'Web, API & data')),
  row('shared', 'ui-0', 'not-installed', ['design', 'frontend', 'mobile', 'productivity'], 'Design & UX'),
  row('claude', 'ui-1', 'not-installed', ['design', 'aardvark'], 'Design & UX'),
  row('shared', 'plain-0', 'not-installed'),
]
const WITH_ROWS = { canned: { 'status --json': json(ROWS) } }

type Opened = Awaited<ReturnType<typeof openTo>>['ui']

const choices = async (ui: Opened, key: string) =>
  ((await ui.find({ key }))?.props.options as Choice[] | undefined) ?? []
const valueOf = async (ui: Opened, key: string) => (await ui.find({ key }))?.props.value
const installKeys = async (ui: Opened) => (await buttonKeys(ui)).filter(key => key.startsWith('install:'))
const cardKeys = async (ui: Opened) =>
  (await ui.findAll({ type: 'Box' })).map(box => box.key ?? '').filter(key => key.startsWith('card:'))
const pairs = (options: Choice[]) => options.map(option => [option.value, option.label])

for (const surface of SURFACES) {
  test(`${surface}: Install has a Tag Select beside the chips: All tags, then the present tags in canonical order with counts`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, WITH_ROWS, 'install')

    const select = await ui.find({ key: 'tag:install' })
    expect(select?.props.label).toBe('Tag')
    expect(select?.props.value).toBe('all')
    // canonical order (design before backend), the order the rows came in does not matter; unknown tags
    // follow alphabetically; only the missing skills count (the installed ones add none), the untagged add none
    expect(pairs(await choices(ui, 'tag:install'))).toEqual([
      ['all', 'All tags'],
      ['design', 'design (2)'],
      ['frontend', 'frontend (1)'],
      ['backend', 'backend (7)'],
      ['api', 'api (7)'],
      ['mobile', 'mobile (1)'],
      ['productivity', 'productivity (1)'],
      ['aardvark', 'aardvark (1)'],
      ['zebra', 'zebra (1)'],
    ])

    // on the chips' own row: the chips and the Select share one row box, the chips still work
    expect((await ui.find({ key: 'filters:install' }))?.props.flexDirection).toBe('row')
    expect(await isActive(ui, 'All')).toBe(true)
    expect(await labelOf(ui, 'install-scope:claude')).toBe('Claude')
    await ui.unmount()
  })

  test(`${surface}: Installed has the same Select over the skills on disk, counted per tag`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, WITH_ROWS, 'installed')

    expect((await ui.find({ key: 'tag:installed' }))?.props).toMatchObject({ label: 'Tag', value: 'all' })
    // only what is on disk counts: the missing skills' tags (mobile, zebra, ...) are not offered here
    expect(pairs(await choices(ui, 'tag:installed'))).toEqual([
      ['all', 'All tags'],
      ['design', 'design (1)'],
      ['frontend', 'frontend (1)'],
      ['backend', 'backend (1)'],
      ['api', 'api (1)'],
      ['orchestration', 'orchestration (6)'],
      ['workflows', 'workflows (6)'],
    ])
    expect((await ui.find({ key: 'filters:installed' }))?.props.flexDirection).toBe('row')
    await ui.unmount()
  })

  test(`${surface}: picking a tag filters the Install cards, goes back to page 1 and narrows Install all`, AT_REPO, async ($, on) => {
    const { w, ui, after } = await openTo($, on, surface, WITH_ROWS, 'install')

    expect(await textCount(ui, /^Showing 1-5 of 10$/)).toBe(1)
    await ui.press({ key: 'next:install' })
    expect(await textCount(ui, /^Showing 6-10 of 10$/)).toBe(1)

    await ui.select({ key: 'tag:install', value: 'backend' })
    expect(await valueOf(ui, 'tag:install')).toBe('backend')
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

    // it combines with the scope chips; All tags lifts it
    await ui.select({ key: 'tag:install', value: 'design' })
    expect(await installKeys(ui)).toEqual(['install:shared/ui-0', 'install:claude/ui-1'])
    await ui.press({ key: 'install-scope:claude' })
    expect(await installKeys(ui)).toEqual(['install:claude/ui-1'])
    await ui.select({ key: 'tag:install', value: 'all' })
    expect(await installKeys(ui)).toEqual(['install:claude/ui-1'])
    await ui.press({ key: 'install-scope:all' })
    expect(await textCount(ui, /^Showing 1-5 of 10$/)).toBe(1)
    await ui.unmount()
  })

  test(`${surface}: a skill matches when the picked tag is any of its tags, drawn on its card or not`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, WITH_ROWS, 'install')

    // `api` is the second tag of every web skill; `productivity` is the fourth tag of ui-0, which its card does not draw
    await ui.select({ key: 'tag:install', value: 'api' })
    expect(await textCount(ui, /^Showing 1-5 of 7$/)).toBe(1)
    await ui.select({ key: 'tag:install', value: 'productivity' })
    expect(await installKeys(ui)).toEqual(['install:shared/ui-0'])
    await ui.select({ key: 'tag:install', value: 'zebra' })
    expect(await installKeys(ui)).toEqual(['install:shared/web-0'])
    await ui.unmount()
  })

  test(`${surface}: a skill with no tags is listed under All tags and under no tag`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, WITH_ROWS, 'install')

    await ui.press({ key: 'next:install' })
    expect(await installKeys(ui)).toContain('install:shared/plain-0')
    // no title text between its scope and its badge
    const texts = await allText(ui)
    const at = texts.indexOf('plain-0')
    expect(texts.slice(at, at + 3)).toEqual(['plain-0', isDesktop(surface) ? 'shared' : '[shared]', badgeText(surface, '· missing')])

    // no option of the Select lists it
    for (const option of await choices(ui, 'tag:install')) {
      if (option.value === 'all') continue
      await ui.select({ key: 'tag:install', value: option.value })
      expect(await installKeys(ui)).not.toContain('install:shared/plain-0')
    }
    await ui.select({ key: 'tag:install', value: 'all' })
    await ui.press({ key: 'next:install' })
    expect(await installKeys(ui)).toContain('install:shared/plain-0')

    // the same on disk
    await ui.press({ key: 'view-installed' })
    await ui.press({ key: 'next:installed' })
    expect(await cardKeys(ui)).toContain('card:claude/inst-plain')
    for (const option of await choices(ui, 'tag:installed')) {
      if (option.value === 'all') continue
      await ui.select({ key: 'tag:installed', value: option.value })
      expect(await cardKeys(ui)).not.toContain('card:claude/inst-plain')
    }
    await ui.unmount()
  })

  test(`${surface}: the card title row holds the name, the scope, then up to three tags dim`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, WITH_ROWS, 'install')
    await ui.press({ key: 'next:install' })

    const texts = await allText(ui)
    const at = texts.indexOf('ui-0')
    const scope = isDesktop(surface) ? 'shared' : '[shared]'
    // four tags, three drawn: the fourth is one pick away in the Select
    expect(texts.slice(at, at + 4)).toEqual(['ui-0', scope, '· design · frontend · mobile', badgeText(surface, '· missing')])
    expect((await ui.find({ type: 'Text', text: /^· design · frontend · mobile$/ }))?.props.dimColor).toBe(true)
    expect(await textCount(ui, /productivity/)).toBe(0)
    expect(await textCount(ui, /^· design · aardvark$/)).toBe(1)
    expect(await textCount(ui, /^· backend · api( · zebra)?$/)).toBe(2)

    // on the Installed cards too, and the category the installer still sends is not drawn anywhere
    await ui.press({ key: 'view-installed' })
    expect(await textCount(ui, /^· orchestration · workflows$/)).toBe(5)
    expect(await textCount(ui, /Orchestration|Design & UX|Web, API/)).toBe(0)
    await ui.unmount()
  })

  test(`${surface}: the Updates cards show the tags of a skill the machine knows`, AT_REPO, async ($, on) => {
    const changed = [{ scope: 'shared', name: 'orch-0', files: ['SKILL.md'] }, { scope: 'shared', name: 'unknown', files: ['SKILL.md'] }]
    const canned = { ...WITH_ROWS.canned, 'updates --json': json({ git: {}, commits: [], changed }) }
    const { ui } = await openTo($, on, surface, { canned }, 'updates')

    expect(await textCount(ui, /^· orchestration · workflows$/)).toBe(1)
    expect((await cardKeys(ui)).filter(key => key.startsWith('card:shared/'))).toEqual(['card:shared/orch-0', 'card:shared/unknown'])
    // the unknown skill has no row to take tags from: nothing sits between its scope and its badge
    const texts = await allText(ui)
    const at = texts.indexOf('unknown')
    expect(texts[at + 2]).toMatch(/not on this machine/)
    await ui.unmount()
  })

  test(`${surface}: with nothing under the tag the Install view says so and offers all tags`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, WITH_ROWS, 'install')

    // the claude scope holds one design skill and no api skill: an api pick over it shows nothing
    await ui.select({ key: 'tag:install', value: 'api' })
    await ui.press({ key: 'install-scope:claude' })
    expect(await installKeys(ui)).toEqual([])
    expect(await textCount(ui, /^No skill tagged api matches\.$/)).toBe(1)
    expect(await textCount(ui, /^No missing skill matches this filter\.$/)).toBe(0)
    expect(await labelOf(ui, 'install-show-all-tags')).toBe('Show all tags')
    expect(await ui.find({ key: 'install-all' })).toBeUndefined()

    await ui.press({ key: 'install-show-all-tags' })
    expect(await valueOf(ui, 'tag:install')).toBe('all')
    expect(await installKeys(ui)).toEqual(['install:claude/ui-1'])
    expect(await textCount(ui, /^No skill tagged /)).toBe(0)

    // when lifting the tag would show nothing either, the generic sentence stays
    await ui.select({ key: 'tag:install', value: 'design' })
    await ui.input({ key: 'install-query', text: 'zzz', kind: 'change' })
    expect(await textCount(ui, /^No missing skill matches this filter\.$/)).toBe(1)
    expect(await textCount(ui, /^No skill tagged /)).toBe(0)
    await ui.unmount()
  })

  test(`${surface}: Installed: a pick filters, resets the page, and an empty tag is named`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, WITH_ROWS, 'installed')

    expect(await textCount(ui, /^Showing 1-5 of 9$/)).toBe(1)
    await ui.press({ key: 'next:installed' })
    expect(await textCount(ui, /^Showing 6-9 of 9$/)).toBe(1)

    await ui.select({ key: 'tag:installed', value: 'orchestration' })
    expect(await textCount(ui, /^Showing 1-5 of 6$/)).toBe(1)
    expect((await cardKeys(ui)).every(key => key.startsWith('card:shared/orch-'))).toBe(true)
    await ui.select({ key: 'tag:installed', value: 'design' })
    expect(await cardKeys(ui)).toEqual(['card:claude/inst-ui'])

    // the chips narrow within the tag; a Modified chip finds none under design
    await ui.press({ key: 'installed-filter:modified' })
    expect(await cardKeys(ui)).toEqual([])
    expect(await textCount(ui, /^No skill tagged design matches\.$/)).toBe(1)
    expect(await labelOf(ui, 'installed-show-all-tags')).toBe('Show all tags')
    await ui.press({ key: 'installed-show-all-tags' })
    expect(await valueOf(ui, 'tag:installed')).toBe('all')
    expect(await cardKeys(ui)).toEqual(['card:claude/mod-web'])

    // nothing matches even with every tag (no skill has a problem): the generic sentence
    await ui.select({ key: 'tag:installed', value: 'orchestration' })
    await ui.press({ key: 'installed-filter:problems' })
    expect(await textCount(ui, /^No skill matches this filter\.$/)).toBe(1)
    expect(await textCount(ui, /^No skill tagged /)).toBe(0)
    await ui.unmount()
  })

  test(`${surface}: jumping to Installed from Overview lifts a tag pick so the count matches`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, WITH_ROWS, 'installed')

    await ui.select({ key: 'tag:installed', value: 'orchestration' })
    await ui.press({ key: 'view-overview' })
    await ui.press({ key: 'attention-modified' })
    expect(await isActive(ui, 'Installed')).toBe(true)
    expect(await valueOf(ui, 'tag:installed')).toBe('all')
    expect(await cardKeys(ui)).toEqual(['card:claude/mod-web'])
    await ui.unmount()
  })

  test(`${surface}: Overview's Install missing still installs every missing skill whatever the Install view was set to`, AT_REPO, async ($, on) => {
    const { w, ui, after } = await openTo($, on, surface, WITH_ROWS, 'install')
    await ui.select({ key: 'tag:install', value: 'design' })
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
      expect((await ui.find({ key: `tag:${view}` }))?.props.label).toBe('Tag')
      expect(Math.max(...(await allText(ui)).map(line => line.length))).toBeLessThanOrEqual(40)
    }
    await ui.unmount()
  })

  test(`${surface}: a card's tags are cut to the room beside its scope and badge`, AT_REPO, async ($, on) => {
    world(on, WITH_ROWS)
    await $.command.run(run('skills'))
    const ui = await mountPane($, surface, { ...PANE, bodyColumns: 50 })
    await ui.press({ key: 'view-install' })
    await ui.select({ key: 'tag:install', value: 'mobile' })

    expect(await installKeys(ui)).toEqual(['install:shared/ui-0'])
    const cut = (await allText(ui)).find(line => line.startsWith('· design'))
    expect(cut?.endsWith('…')).toBe(true)
    expect(cut?.length).toBeLessThan('· design · frontend · mobile'.length)
    expect(Math.max(...(await allText(ui)).map(line => line.length))).toBeLessThanOrEqual(50)
    await ui.unmount()
  })

  test(`${surface}: with no row carrying a tag the Select is not drawn`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, { canned: { 'status --json': json([]) } }, 'install')
    expect(await ui.find({ key: 'tag:install' })).toBeUndefined()
    await ui.press({ key: 'view-installed' })
    expect(await ui.find({ key: 'tag:installed' })).toBeUndefined()
    await ui.unmount()
  })

  test(`${surface}: an installer that sends no tags, or junk in their place, still lists every skill`, AT_REPO, async ($, on) => {
    const junk = [
      row('shared', 'a', 'not-installed'),
      skill('shared', 'b', 'not-installed', { tags: 'design' }),
      skill('shared', 'c', 'not-installed', { tags: [1, null, '  '] }),
    ]
    const { ui } = await openTo($, on, surface, { canned: { 'status --json': json(junk) } }, 'install')
    expect(await installKeys(ui)).toEqual(['install:shared/a', 'install:shared/b', 'install:shared/c'])
    expect(await ui.find({ key: 'tag:install' })).toBeUndefined()
    await ui.unmount()
  })
}
