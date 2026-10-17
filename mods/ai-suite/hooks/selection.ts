// Pure helpers behind the ticked skills of the Install and Installed views: toggling and
// pruning the `scope/name` keys, which rows a selection still names, how a bulk action groups
// them for the CLI (one call per scope) and the names a confirm card lists. No `$` in here.
import type { AiSuiteSkillRow } from '../types'
import type { Named, SelectList } from './commands'
import { ON_DISK, missingRows, plural } from './summary'

/** Names a confirm card lists before it says `and N more`. */
export const NAMES_SHOWN = 8

const keyOf = (row: Named): string => `${row.scope}/${row.name}`

/** `scope/name` back into its two parts; null for anything that is not one. */
export function splitKey(key: string): Named | null {
  const cut = key.indexOf('/')
  return cut <= 0 || cut === key.length - 1 ? null : { scope: key.slice(0, cut), name: key.slice(cut + 1) }
}

/** The keys with `key` added when it was not there and taken out when it was. */
export const toggled = (keys: readonly string[], key: string): string[] =>
  keys.includes(key) ? keys.filter(each => each !== key) : [...keys, key]

/** The keys with `more` added after them, each once. */
export const merged = (keys: readonly string[], more: readonly string[]): string[] => [
  ...keys,
  ...more.filter((key, at) => !keys.includes(key) && more.indexOf(key) === at),
]

export const without = (keys: readonly string[], gone: readonly string[]): string[] =>
  keys.filter(key => !gone.includes(key))

/** The rows a list can tick: the missing skills on Install, the ones on this machine on Installed. */
export const tickable = (rows: readonly AiSuiteSkillRow[], list: SelectList): AiSuiteSkillRow[] =>
  list === 'install' ? missingRows(rows) : rows.filter(row => ON_DISK.includes(row.state))

/** The ticked keys that still name a row of the list (a rescan drops the rest). */
export function keepKnown(keys: readonly string[], rows: readonly AiSuiteSkillRow[], list: SelectList): string[] {
  const known = new Set(tickable(rows, list).map(keyOf))
  return keys.filter(key => known.has(key))
}

/** The rows a selection names, in the rows' own order. */
export const chosenRows = (rows: readonly AiSuiteSkillRow[], keys: readonly string[]): AiSuiteSkillRow[] =>
  rows.filter(row => keys.includes(keyOf(row)))

/** What each Installed bulk button applies to among the ticked rows. */
export type InstalledPlan = {
  update: AiSuiteSkillRow[]
  relink: AiSuiteSkillRow[]
  retire: AiSuiteSkillRow[]
}

export const installedPlan = (chosen: readonly AiSuiteSkillRow[]): InstalledPlan => ({
  update: chosen.filter(row => row.state === 'modified'),
  relink: chosen.filter(row => row.canRelink),
  retire: chosen.filter(row => row.canRetire),
})

export type Group = { scope: string; names: string[] }

/** The keys grouped by scope in order of first appearance; a key that is not `scope/name` is left out. */
export function groupByScope(keys: readonly string[]): Group[] {
  const named = keys.flatMap(key => {
    const part = splitKey(key)
    return part === null ? [] : [part]
  })
  return [...new Set(named.map(item => item.scope))].map(scope => ({
    scope,
    names: named.filter(item => item.scope === scope).map(item => item.name),
  }))
}

/** `a, b, c` for a few keys; the first eight then `and N more` for many. */
export function namesLine(keys: readonly string[]): string {
  if (keys.length <= NAMES_SHOWN) return keys.join(', ')
  return `${keys.slice(0, NAMES_SHOWN).join(', ')} and ${keys.length - NAMES_SHOWN} more`
}

export const skillsOf = (count: number): string => plural(count, 'skill', 'skills')
