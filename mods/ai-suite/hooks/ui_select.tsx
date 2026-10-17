// The selection bar: the card that appears above a list once skills are ticked. It says how many
// are ticked, holds the buttons of what can be done to all of them, and gives its place to the
// confirm card while a bulk Retire waits for an answer.
import { barAnchor } from './commands'
import type { Act, BulkVerb, SelectList } from './commands'
import { actButton, actionRow, card, heading } from './ui'
import type { Env } from './ui'
import { confirmAfter } from './ui_parts'

/** One verb of the bar: the skills it applies to (`scope/name` keys), its label, and whether it asks first. */
export type BarVerb = {
  verb: BulkVerb
  ids: readonly string[]
  label: string
  isPrimary?: true
  /** A bulk Retire: the press arms the confirm card, which is drawn in the bar's place. */
  isConfirmed?: true
}

export type SelectionBar = {
  list: SelectList
  /** The ticked skills the list still holds (what the title counts). */
  count: number
  /** The keys of every skill the current filters show, across pages. */
  shownIds: readonly string[]
  verbs: readonly BarVerb[]
}

function verbAct(list: SelectList, spec: BarVerb): Act {
  const command = { kind: 'bulk' as const, list, verb: spec.verb, ids: [...spec.ids] }
  const key = `bulk-${spec.verb}`
  return spec.isConfirmed === true ? { key, command, confirm: true, anchor: barAnchor(list) } : { key, command }
}

/** `N selected` with the bar's buttons, or the confirm card when a bulk action of this list is waiting for an answer. */
export function selectionBar(env: Env, bar: SelectionBar): JSX.Element {
  const asked = confirmAfter(env, barAnchor(bar.list))
  if (asked !== null) return asked
  const { list } = bar
  return card(
    env,
    `selection-bar:${list}`,
    'magenta',
    heading(env, `${bar.count} selected`),
    actionRow(
      env,
      ...bar.verbs.map(spec => actButton(env, verbAct(list, spec), spec.label, spec.isPrimary === true ? { primary: true } : {})),
      bar.shownIds.length > 0 &&
        actButton(
          env,
          { key: `select-all:${list}`, command: { kind: 'select-all', list, ids: [...bar.shownIds] } },
          `Select all shown (${bar.shownIds.length})`,
        ),
      actButton(env, { key: `clear-selection:${list}`, command: { kind: 'clear-selection', list } }, 'Clear'),
    ),
  )
}
