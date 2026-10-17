// The $.state contract of the ai-suite mod: every named value it keeps in the
// session, declared once under PluginState['ai-suite'].

export type AiSuiteView = 'overview' | 'install' | 'issues' | 'updates' | 'workflows' | 'doctor'

/** One command's last answer: its parsed data, when it landed (ms) and its last error. */
export type AiSuiteSnapshot<T> = {
  data: T | null
  fetchedAt: number | null
  error: string | null
}

/** One row of `status --json`, reduced to what the pane counts. */
export type AiSuiteSkillRow = {
  scope: string
  name: string
  state: string
  hasSource: boolean
  hasProblem: boolean
  hasRemote: boolean
}

/** One row of `list --json`: a skill the repo offers and whether it is installed. */
export type AiSuiteCatalogRow = {
  scope: string
  name: string
  state: string
  installed: string
  description: string
}

/** One entry of `issues --json` problems, with the repairs the pane may offer. */
export type AiSuiteProblem = {
  scope: string
  name: string
  state: string
  text: string
  canRelink: boolean
  canRetire: boolean
}

export type AiSuiteRepoIssue = { scope: string; name: string; message: string }
export type AiSuiteIssues = { problems: AiSuiteProblem[]; repoIssues: AiSuiteRepoIssue[] }

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

/** The last answer of each read command, one snapshot per command. */
export type AiSuiteSnapshots = {
  status: AiSuiteSnapshot<AiSuiteSkillRow[]>
  catalog: AiSuiteSnapshot<AiSuiteCatalogRow[]>
  issues: AiSuiteSnapshot<AiSuiteIssues>
  updates: AiSuiteSnapshot<AiSuiteUpdates>
  workflows: AiSuiteSnapshot<AiSuiteWorkflow[]>
  doctor: AiSuiteSnapshot<AiSuiteDoctor>
}

/** The pane's message row. */
export type AiSuiteMessage = { kind: 'info' | 'ok' | 'error'; text: string }

/** A command in flight: what it is and when it began (ms); stale after ten minutes. */
export type AiSuiteBusy = { label: string; since: number }

/** The repo the last resolution settled on; `error` is empty when it was found. */
export type AiSuiteRepo = { path: string; shown: string; error: string }

declare module 'claude-code' {
  interface PluginState {
    'ai-suite': {
      view: AiSuiteView
      page: number
      repo: AiSuiteRepo | null
      snapshots: AiSuiteSnapshots
      busy: AiSuiteBusy | null
      pendingConfirm: string | null
      message: AiSuiteMessage | null
    }
  }
}
