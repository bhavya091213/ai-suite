// The Settings view as data: which settings it shows, in which sections, and the
// preset values each Select offers. Free text is only ever reached through `Custom…`. The
// skill categories the Install and Installed views filter by live here too.

/** The option value that reveals a text field. */
export const CUSTOM = '__custom__'
/** The option value that stands for an empty setting (no default vault, the default editor). */
export const NONE = '__none__'

export type Option = { value: string; label?: string }

/** `select` is a plain preset list; `vault` and `path` are the Paths section's own controls. */
export type SettingKind = 'select' | 'vault' | 'path'

export type SettingSpec = {
  key: string
  label: string
  kind: SettingKind
  options: readonly Option[]
  /** True when the list ends with `Custom…`. */
  hasCustom: boolean
}

export type SettingSection = { id: string; title: string; settings: readonly SettingSpec[] }

const words = (...values: string[]): Option[] => values.map(value => ({ value }))
const pick = (key: string, label: string, options: readonly Option[], hasCustom = false): SettingSpec => ({
  key,
  label,
  kind: 'select',
  options,
  hasCustom,
})

const TOOL_MODES = words('auto', 'on', 'off')
const ON_OFF = words('on', 'off')
const CLAUDE_MODELS = words(
  'opus',
  'sonnet',
  'haiku',
  'claude-opus-5-5',
  'claude-sonnet-5-5',
  'claude-haiku-5-5',
  'claude-fable-5-1',
)
const EFFORTS = words('low', 'medium', 'high', 'xhigh', 'max')
const BUDGETS: Option[] = [50, 100, 150, 200].map(k => ({ value: String(k * 1000), label: `${k}k` }))

export const SECTIONS: readonly SettingSection[] = [
  {
    id: 'tools',
    title: 'Tools',
    settings: [
      pick('tools.claude', 'Claude Code', TOOL_MODES),
      pick('tools.codex', 'Codex CLI', TOOL_MODES),
    ],
  },
  {
    id: 'claude',
    title: 'Claude models',
    settings: [
      pick('subagents.claude.heavy', 'Heavy tier', CLAUDE_MODELS, true),
      pick('subagents.claude.light', 'Light tier', CLAUDE_MODELS, true),
      pick('subagents.claude.trivial', 'Trivial tier', CLAUDE_MODELS, true),
    ],
  },
  {
    id: 'codex',
    title: 'Codex',
    settings: [
      pick('subagents.codex.model', 'Model', words('gpt-5.6-sol', 'gpt-5.5', 'gpt-6-astra'), true),
      pick('subagents.codex.heavy', 'Heavy effort', EFFORTS),
      pick('subagents.codex.light', 'Light effort', EFFORTS),
      pick('subagents.codex.trivial', 'Trivial effort', EFFORTS),
      pick('subagents.codex.max_threads', 'Max threads', words('1', '2', '4', '6', '8', '12')),
      pick('subagents.codex.max_depth', 'Max depth', words('1', '2', '3')),
    ],
  },
  {
    id: 'review',
    title: 'Review',
    settings: [pick('review.adversarial', 'Adversarial reviewer', words('auto', 'codex', 'claude'))],
  },
  {
    id: 'guardrails',
    title: 'Guardrails',
    settings: [
      pick('guardrails.never_delete', 'Never delete (mv, not rm)', ON_OFF),
      pick('guardrails.context_budget_tokens', 'Context budget', BUDGETS),
      pick('guardrails.preflight_checklist', 'Pre-flight checklist', ON_OFF),
      pick('guardrails.plan_approval_gate', 'Plan approval gate', ON_OFF),
      pick('guardrails.fix_approval_gate', 'Fix approval gate', ON_OFF),
      pick('guardrails.hook_profile', 'Hook profile', words('minimal', 'standard', 'strict')),
    ],
  },
  {
    id: 'paths',
    title: 'Paths',
    settings: [
      { key: 'paths.obsidian_vaults', label: 'Default Obsidian vault', kind: 'vault', options: [], hasCustom: true },
      { key: 'paths.sessions_dir', label: 'Sessions folder', kind: 'path', options: [], hasCustom: true },
      { key: 'paths.backups_dir', label: 'Backups folder', kind: 'path', options: [], hasCustom: true },
    ],
  },
  {
    id: 'editor',
    title: 'Editor',
    settings: [
      pick(
        'editor',
        'Editor command',
        [{ value: NONE, label: 'default ($VISUAL / $EDITOR)' }, ...words('nano', 'vim', 'vi', 'code --wait')],
        true,
      ),
    ],
  },
]

export const ALL_SETTINGS: readonly SettingSpec[] = SECTIONS.flatMap(section => section.settings)

export function specOf(key: string): SettingSpec | undefined {
  return ALL_SETTINGS.find(spec => spec.key === key)
}

/** The sentence a setting is named by (`Heavy tier`), or its raw key when it is not one of ours. */
export const settingLabel = (key: string): string => specOf(key)?.label ?? key

export type SelectChoice = { options: Option[]; value: string }

/**
 * The options a Select shows for `current` and which one is selected. A current value that
 * is not in the preset list is added at the top, so it is always visible; `isCustomOpen`
 * selects `Custom…` while its text field is up.
 */
export function selectChoice(spec: SettingSpec, current: string, isCustomOpen: boolean): SelectChoice {
  const hasNone = spec.options.some(option => option.value === NONE)
  const shown = current === '' && hasNone ? NONE : current
  const isKnown = spec.options.some(option => option.value === shown)
  const extra: Option[] = isKnown || shown === '' ? [] : [{ value: shown, label: `${shown} (current)` }]
  const custom: Option[] = spec.hasCustom ? [{ value: CUSTOM, label: 'Custom…' }] : []
  const options = [...extra, ...spec.options, ...custom]
  const fallback = spec.options[0]?.value ?? ''
  return { options, value: isCustomOpen ? CUSTOM : shown === '' ? fallback : shown }
}

/** The text `config set` takes for a picked value (an empty setting is empty text). */
export const settingText = (value: string): string => (value === NONE ? '' : value)

// ------------------------------------------------------------ skill categories

/** The category of a skill the installer gives none (and the last in the list). */
export const OTHER_CATEGORY = 'Other'
/** The category Select's value for every category. */
export const ALL_CATEGORIES = 'all'
/** The canonical order of the categories: `order` of shared/skill-categories.json. */
export const CATEGORY_ORDER: readonly string[] = [
  'Orchestration',
  'Engineering practice',
  'Languages & frameworks',
  'Web, API & data',
  'Design & UX',
  'Research & knowledge',
  'Content & media',
  'Presentations',
  'Business & career',
  OTHER_CATEGORY,
]

/** Where a category sorts: canonical order, a name the installer added just before Other, Other last. */
function categoryRank(category: string): number {
  if (category === OTHER_CATEGORY) return CATEGORY_ORDER.length
  const at = CATEGORY_ORDER.indexOf(category)
  return at >= 0 ? at : CATEGORY_ORDER.length - 1
}

/**
 * The category Select's options: `All categories`, then the categories `present` in the rows in
 * canonical order. The `current` pick is kept in the list even when no row has it any more, so
 * the Select never holds a value it cannot show.
 */
export function categoryOptions(present: readonly string[], current: string): Option[] {
  const wanted = current === ALL_CATEGORIES ? present : [...present, current]
  const sorted = [...new Set(wanted)].sort((a, b) => categoryRank(a) - categoryRank(b) || a.localeCompare(b))
  return [{ value: ALL_CATEGORIES, label: 'All categories' }, ...sorted.map(value => ({ value }))]
}
