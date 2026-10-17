// Settings: ~/.agents/config.json as cards of Selects. Every pick is written at once with
// `config set`; free text is only reached through `Custom…` (or `Change…` for the two folders).
import type { AiSuiteConfig } from '../types'
import { shortenHome } from './cli'
import { rowAnchor } from './commands'
import type { Command } from './commands'
import { CUSTOM, NONE, SECTIONS, selectChoice, settingText } from './presets'
import type { SettingSection, SettingSpec } from './presets'
import { above, actButton, actionRow, buttonRow, card, column, entry, fit, heading, line, linesOf } from './ui'
import type { Env } from './ui'
import { LABEL_WIDTH, confirmAfter, indent, labelCell, note, pickRow } from './ui_parts'

const OUTPUT_LINES = 14

/** Section title and setting label for every key, for the Reset list. */
const RESET_OPTIONS = [
  { value: NONE, label: 'a setting…' },
  ...SECTIONS.flatMap(section =>
    section.settings.map(spec => ({ value: spec.key, label: `${section.title}: ${spec.label}` })),
  ),
]

/** The text field behind `Custom…` / `Change…`, with its Cancel. */
function customField(env: Env, spec: SettingSpec, start: string): JSX.Element {
  const { Box, Input } = env.els
  const submit = (text: string): Promise<void> =>
    text.trim() === ''
      ? env.dispatch({ key: `custom-cancel:${spec.key}`, command: { kind: 'custom', key: null } })
      : env.dispatch({ key: `set:${spec.key}`, command: { kind: 'set', key: spec.key, value: text.trim() } })
  return (
    <Box key={`custom-row:${spec.key}`} flexDirection="row" gap={1} {...indent(env)}>
      <Input
        key={`custom-input:${spec.key}`}
        label="Custom"
        placeholder="type a value, then Enter"
        value={start}
        submitLabel="save"
        autoFocus
        onSubmit={submit}
      />
      {actButton(env, { key: `custom-cancel:${spec.key}`, command: { kind: 'custom', key: null } }, 'Cancel')}
    </Box>
  )
}

function presetRow(env: Env, spec: SettingSpec, values: AiSuiteConfig): JSX.Element {
  const { Box } = env.els
  const current = values[spec.key] ?? ''
  const isCustom = env.data.customKey === spec.key
  const choice = selectChoice(spec, current, isCustom)
  const onSelect = (value: string): Promise<void> => {
    if (value === CUSTOM) return env.dispatch({ key: `custom:${spec.key}`, command: { kind: 'custom', key: spec.key } })
    const text = settingText(value)
    const command: Command =
      text === current ? { kind: 'custom', key: null } : { kind: 'set', key: spec.key, value: text }
    return env.dispatch({ key: `set:${spec.key}`, command })
  }
  return (
    <Box flexDirection="column">
      {pickRow(env, `set:${spec.key}`, spec.label, { options: choice.options, value: choice.value, onSelect })}
      {isCustom && customField(env, spec, '')}
    </Box>
  )
}

/** The default vault is the first in `paths.obsidian_vaults`; picking one puts it first and keeps the rest. */
function vaultRow(env: Env, spec: SettingSpec, values: AiSuiteConfig): JSX.Element {
  const { Box } = env.els
  const home = env.data.repo?.home ?? ''
  const known = env.data.snapshots.caps.data?.vaults ?? []
  const saved = (values[spec.key] ?? '').split(',').filter(path => path !== '')
  const current = saved[0] ?? ''
  const isCustom = env.data.customKey === spec.key
  const extra = current !== '' && !known.includes(current) ? [current] : []
  const options = [
    ...[...extra, ...known].map(path => ({ value: path, label: shortenHome(path, home) })),
    { value: NONE, label: 'None' },
    { value: CUSTOM, label: 'Custom…' },
  ]
  const onSelect = (value: string): Promise<void> => {
    if (value === CUSTOM) return env.dispatch({ key: `custom:${spec.key}`, command: { kind: 'custom', key: spec.key } })
    const list = (value === NONE ? [] : [value, ...saved.filter(path => path !== value)]).join(',')
    const command: Command =
      list === saved.join(',') ? { kind: 'custom', key: null } : { kind: 'set', key: spec.key, value: list }
    return env.dispatch({ key: `set:${spec.key}`, command })
  }
  return (
    <Box flexDirection="column">
      {pickRow(env, `set:${spec.key}`, spec.label, {
        options,
        value: isCustom ? CUSTOM : current === '' ? NONE : current,
        onSelect,
      })}
      {isCustom && customField(env, spec, '')}
    </Box>
  )
}

function pathRow(env: Env, spec: SettingSpec, values: AiSuiteConfig): JSX.Element {
  const { Box, Text } = env.els
  const current = values[spec.key] ?? ''
  const isCustom = env.data.customKey === spec.key
  return (
    <Box flexDirection="column">
      <Box flexDirection="row" gap={env.isDesktop ? 2 : 1} justifyContent="space-between" alignItems="center">
        <Box flexDirection="row">
          {labelCell(env, spec.label)}
          <Text wrap="truncate">{fit(env, current, LABEL_WIDTH + 14)}</Text>
        </Box>
        {actButton(env, { key: `change:${spec.key}`, command: { kind: 'custom', key: isCustom ? null : spec.key } }, isCustom ? 'Close' : 'Change…')}
      </Box>
      {isCustom && customField(env, spec, current)}
    </Box>
  )
}

function settingRow(env: Env, spec: SettingSpec, values: AiSuiteConfig): JSX.Element {
  if (spec.kind === 'vault') return vaultRow(env, spec, values)
  return spec.kind === 'path' ? pathRow(env, spec, values) : presetRow(env, spec, values)
}

function sectionCard(env: Env, section: SettingSection, values: AiSuiteConfig): JSX.Element {
  return card(
    env,
    `section:${section.id}`,
    null,
    heading(env, section.title),
    entry(env, ...section.settings.map(spec => settingRow(env, spec, values))),
  )
}

/** Apply (a confirm card first) and the reset list (every key, then a confirm card). */
function footerCard(env: Env): JSX.Element {
  const reset = (key: string): Promise<void> =>
    key === NONE
      ? Promise.resolve()
      : env.dispatch({ key: 'reset-setting', command: { kind: 'reset', key }, confirm: true, anchor: rowAnchor('settings-reset') })
  return card(
    env,
    'settings-actions',
    null,
    heading(env, 'Apply and reset'),
    line(env, 'Picks are saved as you make them. Apply copies them into the tools on this machine.', 'dim'),
    actionRow(
      env,
      actButton(
        env,
        { key: 'apply', command: { kind: 'apply' }, confirm: true, anchor: rowAnchor('settings-apply') },
        'Apply to this machine…',
        { primary: true },
      ),
    ),
    confirmAfter(env, rowAnchor('settings-apply')),
    pickRow(env, 'reset-setting', 'Reset', { options: RESET_OPTIONS, value: NONE, onSelect: reset }),
    confirmAfter(env, rowAnchor('settings-reset')),
  )
}

function applyOutput(env: Env): JSX.Element | null {
  const detail = env.data.detail
  if (detail === null || detail.kind !== 'apply') return null
  const { Text } = env.els
  const all = linesOf(env, detail.text).filter(each => each.trim() !== '')
  return card(
    env,
    'apply-output',
    null,
    heading(env, 'Apply output'),
    entry(
      env,
      ...all.slice(0, OUTPUT_LINES).map(each => <Text wrap="truncate">{each}</Text>),
      all.length > OUTPUT_LINES && <Text dimColor>{`… ${all.length - OUTPUT_LINES} more lines`}</Text>,
    ),
    buttonRow(env, actButton(env, { key: 'close-apply', command: { kind: 'close-detail' } }, 'Close')),
  )
}

function missingConfig(env: Env, path: string): JSX.Element {
  return card(
    env,
    'config-missing',
    'warning',
    heading(env, 'No config.json yet'),
    line(env, `${shortenHome(path, env.data.repo?.home ?? '')} does not exist, so the defaults apply. Your first pick creates it.`, 'dim'),
    buttonRow(env, actButton(env, { key: 'create-config', command: { kind: 'create-config' } }, 'Create it with defaults', { primary: true })),
  )
}

export function settings(env: Env): JSX.Element {
  const { Box } = env.els
  const { config, configFile } = env.data.snapshots
  const values = config.data
  return (
    <Box {...column(env)}>
      {note(env, config, 'settings')}
      {configFile.data !== null && !configFile.data.exists && missingConfig(env, configFile.data.path)}
      {values !== null && SECTIONS.map(section => sectionCard(env, section, values))}
      {values !== null && footerCard(env)}
      {applyOutput(env)}
      <Box {...above(env)}>{actButton(env, { key: 'refresh', command: { kind: 'refresh' } }, 'Refresh')}</Box>
    </Box>
  )
}
