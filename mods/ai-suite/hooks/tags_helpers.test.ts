// Run with: claude plugin test mods/ai-suite
// The pure side of the tag filter: the canonical order, the Select's options with counts, how
// `status --json` rows are read (a missing or malformed `tags` is none; `category` is still read),
// and the filters and counts built on them. The views are in tags.test.ts.
import { expect, test } from 'claude-code/testing'
import { parseStatus } from './parse'
import { ALL_TAGS, TAG_ORDER, tagOptions } from './presets'
import { filterInstalled, filterMissing, tagCounts } from './summary'
import { skill } from './testkit'

const row = (scope: string, name: string, state: string, tags?: string[], category?: string) =>
  skill(scope, name, state, {
    ...(tags === undefined ? {} : { tags }),
    ...(category === undefined ? {} : { category }),
  })

test('tag order is the canonical list of 23, design first and meta last', () => {
  expect(TAG_ORDER).toEqual([
    'design',
    'frontend',
    'backend',
    'api',
    'mobile',
    'data',
    'coding',
    'testing',
    'quality',
    'security',
    'orchestration',
    'workflows',
    'productivity',
    'learning',
    'research',
    'knowledge',
    'writing',
    'presentations',
    'media',
    'business',
    'career',
    'ml',
    'meta',
  ])
  expect(new Set(TAG_ORDER).size).toBe(TAG_ORDER.length)
})

test('tag options: All tags first, the present tags in canonical order with counts, unknown ones after them, the current pick kept', () => {
  const count = (...tags: string[]) => tags.map(tag => ({ tag, count: 1 }))
  expect(tagOptions([], ALL_TAGS)).toEqual([{ value: 'all', label: 'All tags' }])
  expect(tagOptions([{ tag: 'meta', count: 2 }, { tag: 'design', count: 20 }], ALL_TAGS)).toEqual([
    { value: 'all', label: 'All tags' },
    { value: 'design', label: 'design (20)' },
    { value: 'meta', label: 'meta (2)' },
  ])
  // unknown tags go after the known ones, alphabetically
  expect(tagOptions(count('zebra', 'career', 'alpaca', 'design'), ALL_TAGS).map(option => option.value)).toEqual([
    'all',
    'design',
    'career',
    'alpaca',
    'zebra',
  ])
  // a pick no row carries any more stays in the list, in its place, with a zero
  expect(tagOptions(count('design', 'meta'), 'security').map(option => [option.value, option.label])).toEqual([
    ['all', 'All tags'],
    ['design', 'design (1)'],
    ['security', 'security (0)'],
    ['meta', 'meta (1)'],
  ])
})

test('parseStatus reads tags, treats a missing or malformed field as none, and the filters honour them', () => {
  const rows = parseStatus([
    row('shared', 'a', 'not-installed', ['design', 'frontend'], 'Design & UX'),
    row('shared', 'b', 'not-installed'),
    skill('claude', 'c', 'not-installed', { tags: 'design' }),
    skill('claude', 'd', 'installed', { tags: [' design ', 'design', '', 7, null, 'api'] }),
    skill('claude', 'e', 'installed', { tags: null }),
    row('claude', 'f', 'installed', ['api']),
  ])
  const all = rows ?? []
  expect(all.map(each => each.tags)).toEqual([['design', 'frontend'], [], [], ['design', 'api'], [], ['api']])
  // the category is still read and kept (Other when the installer sends none), only no longer drawn or filtered by
  expect(all.map(each => each.category)).toEqual(['Design & UX', 'Other', 'Other', 'Other', 'Other', 'Other'])

  const none = { installScope: 'all', installQuery: '' } as const
  expect(filterMissing(all, { ...none, installTag: 'all' }).map(each => each.name)).toEqual(['a', 'b', 'c'])
  expect(filterMissing(all, { ...none, installTag: 'design' }).map(each => each.name)).toEqual(['a'])
  expect(filterMissing(all, { installScope: 'claude', installQuery: '', installTag: 'design' })).toEqual([])
  expect(filterMissing(all, { ...none, installTag: 'Design & UX' })).toEqual([])
  expect(filterInstalled(all, 'all', 'api').map(each => each.name)).toEqual(['d', 'f'])
  expect(filterInstalled(all, 'all').map(each => each.name)).toEqual(['d', 'e', 'f'])
  expect(filterInstalled(all, 'all', 'frontend')).toEqual([])
  expect(tagCounts(all)).toEqual([
    { tag: 'design', count: 2 },
    { tag: 'frontend', count: 1 },
    { tag: 'api', count: 2 },
  ])
})
