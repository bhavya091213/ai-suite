// The $.state contract of the ai-suite mod: every named value it keeps in the
// session, declared once under PluginState['ai-suite'].

export type AiSuiteView =
  | 'overview'
  | 'install'
  | 'installed'
  | 'updates'
  | 'settings'
  | 'workflows'
  | 'doctor'

/** One command's last answer: its parsed data, when it landed (ms) and its last error. */
export type AiSuiteSnapshot<T> = {
  data: T | null
  fetchedAt: number | null
  error: string | null
}

/** One consumer's link to a shared skill, as `status --json` reports it (ok, missing, broken, ...). */
export type AiSuiteLink = { consumer: string; state: string }

/** One row of `status --json`, reduced to what the pane draws and counts. */
export type AiSuiteSkillRow = {
  scope: string
  name: string
  state: string
  description: string
  /** The installer's category for the skill (Design & UX, Orchestration, ...); `Other` when it sends none. Kept, but no longer drawn or filtered by. */
  category: string
  /** The skill's use-case tags (`design`, `frontend`, ...), each once; empty when the installer sends none. */
  tags: string[]
  /** The first problem in words (with "(+N more)"), empty when there is none. */
  note: string
  hasSource: boolean
  hasProblem: boolean
  hasRemote: boolean
  canRelink: boolean
  canRetire: boolean
  links: AiSuiteLink[]
}

export type AiSuiteGit = {
  message: string
  hint: string
  branch: string
  upstream: string
  ahead: number
  behind: number
  lastFetch: string
}

export type AiSuiteChanged = { scope: string; name: string; files: number }

export type AiSuiteUpdates = {
  git: AiSuiteGit
  commits: string[]
  changed: AiSuiteChanged[]
}

export type AiSuiteWorkflow = {
  name: string
  phases: number
  skills: number
  valid: boolean
  note: string
}

export type AiSuiteCheckState = 'ok' | 'warn' | 'blocker'
export type AiSuiteDoctorCheck = { name: string; state: AiSuiteCheckState; text: string }
export type AiSuiteDoctor = { checks: AiSuiteDoctorCheck[]; blockers: number }

/** One tool `caps --json` probed: its name, whether it was found and its version line. */
export type AiSuiteTool = { name: string; present: boolean; version: string }
export type AiSuiteCaps = { tools: AiSuiteTool[]; vaults: string[] }

/** Where config.json lives (`config path`) and whether the file is there yet. */
export type AiSuiteConfigFile = { path: string; exists: boolean }

/** `config list --json` flattened to dotted keys; every value is text (booleans are on / off, lists comma-joined). */
export type AiSuiteConfig = Record<string, string>

/** The last answer of each read command, one snapshot per command. */
export type AiSuiteSnapshots = {
  status: AiSuiteSnapshot<AiSuiteSkillRow[]>
  updates: AiSuiteSnapshot<AiSuiteUpdates>
  workflows: AiSuiteSnapshot<AiSuiteWorkflow[]>
  doctor: AiSuiteSnapshot<AiSuiteDoctor>
  caps: AiSuiteSnapshot<AiSuiteCaps>
  configFile: AiSuiteSnapshot<AiSuiteConfigFile>
  config: AiSuiteSnapshot<AiSuiteConfig>
}

export type AiSuiteScopeFilter = 'all' | 'shared' | 'claude' | 'codex'
export type AiSuiteInstalledFilter = 'all' | 'modified' | 'problems' | 'foreign' | 'tool-managed'

/** What the Install and Installed views are narrowed to. A tag filter is `all` or a tag name. */
export type AiSuiteFilters = {
  installScope: AiSuiteScopeFilter
  installQuery: string
  installTag: string
  installed: AiSuiteInstalledFilter
  installedTag: string
}

/** A card shown under a view's list: a skill's file tree, a workflow's SKILL.md, or the apply output. */
export type AiSuiteDetail = { kind: 'files' | 'preview' | 'apply'; id: string; text: string }

/**
 * Where a pending confirm card is drawn: `card` directly under the skill (or workflow) card whose
 * Box key is `key`, `row` directly under the button row named `key`, `bar` in the place of the
 * selection bar of the list named `key`, `top` under the header (nothing more specific was named).
 */
export type AiSuiteAnchor = { kind: 'card' | 'row' | 'bar' | 'top'; key: string }

/** The confirm card that is up: the command it runs on Yes, encoded as text, and where it is drawn. */
export type AiSuiteConfirm = { command: string; anchor: AiSuiteAnchor }

/** The pane's message row. */
export type AiSuiteMessage = { kind: 'info' | 'ok' | 'error'; text: string }

/** A command in flight: what it is and when it began (ms); stale after ten minutes. */
export type AiSuiteBusy = { label: string; since: number }

/** The repo the last resolution settled on (`home` is $HOME, for shortening paths); `error` is empty when it was found. */
export type AiSuiteRepo = { path: string; shown: string; home: string; error: string }

declare module 'claude-code' {
  interface PluginState {
    'ai-suite': {
      view: AiSuiteView
      /** The page each list is on, by list id ('install', 'installed', 'updates', 'workflows', 'preview', 'doctor'). */
      pages: Record<string, number>
      filters: AiSuiteFilters
      repo: AiSuiteRepo | null
      snapshots: AiSuiteSnapshots
      busy: AiSuiteBusy | null
      /** The confirm card that is up: the command it will run if answered Yes (encoded as text) and where it is drawn; null when none. */
      pendingConfirm: AiSuiteConfirm | null
      message: AiSuiteMessage | null
      /** The setting whose Custom... field is open in Settings, or null. */
      customKey: string | null
      /** The skills ticked on the Install view, as `scope/name` keys. */
      installSelection: string[]
      /** The skills ticked on the Installed view, as `scope/name` keys. */
      installedSelection: string[]
      /** The files / preview / apply card under the current view, or null. */
      detail: AiSuiteDetail | null
      /** True once Hide was pressed on the band above the prompt; lasts for the session. */
      bandHidden: boolean
      /** True while the pane opened at session start waits undrawn (the terminal was too narrow). */
      paneWaiting: boolean
    }
  }
}
