// Run with: claude plugin test mods/ai-suite
// The Settings view on both surfaces: a Select per setting with the preset options, picks written
// at once with `config set`, Custom… fields, the missing-config callout, Apply and Reset.
import { expect, test } from 'claude-code/testing'
import { AT_REPO, CONFIG, SURFACES, bad, exact, isDesktop, json, labelOf, openTo, textCount } from './testkit'

type Choice = { value: string; label?: string }

const COPIES = [
  ['tools.claude', ['auto', 'on', 'off'], 'on'],
  ['tools.codex', ['auto', 'on', 'off'], 'auto'],
  ['subagents.claude.heavy', ['opus', 'sonnet', 'haiku', 'claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5', 'claude-fable-5-1', '__custom__'], 'opus'],
  ['subagents.claude.trivial', ['opus', 'sonnet', 'haiku', 'claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5', 'claude-fable-5-1', '__custom__'], 'haiku'],
  ['subagents.codex.model', ['astra', 'gpt-5.6-sol', 'gpt-5.5', 'gpt-6-astra', '__custom__'], 'astra'],
  ['subagents.codex.heavy', ['low', 'medium', 'high', 'xhigh', 'max'], 'xhigh'],
  ['subagents.codex.trivial', ['low', 'medium', 'high', 'xhigh', 'max'], 'low'],
  ['subagents.codex.max_threads', ['1', '2', '4', '6', '8', '12'], '6'],
  ['subagents.codex.max_depth', ['1', '2', '3'], '1'],
  ['review.adversarial', ['auto', 'codex', 'claude'], 'auto'],
  ['guardrails.never_delete', ['on', 'off'], 'on'],
  ['guardrails.context_budget_tokens', ['50000', '100000', '150000', '200000'], '100000'],
  ['guardrails.preflight_checklist', ['on', 'off'], 'on'],
  ['guardrails.plan_approval_gate', ['on', 'off'], 'on'],
  ['guardrails.fix_approval_gate', ['on', 'off'], 'off'],
  ['guardrails.hook_profile', ['minimal', 'standard', 'strict'], 'standard'],
  ['paths.obsidian_vaults', ['/vaults/notes', '/vaults/work', '__none__', '__custom__'], '/vaults/notes'],
  ['editor', ['__none__', 'nano', 'vim', 'vi', 'code --wait', '__custom__'], '__none__'],
] as const

for (const surface of SURFACES) {
  test(`${surface}: Settings has a Select per setting with the preset options and the current value selected`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, {}, 'settings')

    for (const [key, options, selected] of COPIES) {
      const found = await ui.find({ key: `set:${key}` })
      const choices = found?.props.options as Choice[] | undefined
      expect([key, choices?.map(choice => choice.value)]).toEqual([key, options])
      expect([key, found?.props.value]).toEqual([key, selected])
    }
    // the terminal puts the label in the Select; the desktop draws it as a dim cell beside it
    const claude = await ui.find({ key: 'set:tools.claude' })
    expect(claude?.props.label).toBe(isDesktop(surface) ? undefined : 'Claude Code'.padEnd(26))
    expect(await textCount(ui, /^Claude Code$/)).toBe(isDesktop(surface) ? 1 : 0)
    expect((await ui.find({ type: 'Text', text: /^Claude Code$/ }))?.props.dimColor).toBe(isDesktop(surface) ? true : undefined)
    // a current value outside the presets is shown, first; budgets are labelled 50k..200k
    const model = (await ui.find({ key: 'set:subagents.codex.model' }))?.props.options as Choice[]
    expect(model[0]).toEqual({ value: 'astra', label: 'astra (current)' })
    const budget = (await ui.find({ key: 'set:guardrails.context_budget_tokens' }))?.props.options as Choice[]
    expect(budget.map(choice => choice.label)).toEqual(['50k', '100k', '150k', '200k'])

    for (const title of ['Tools', 'Claude models', 'Codex', 'Review', 'Guardrails', 'Paths', 'Editor']) {
      expect(await textCount(ui, new RegExp(`^${title}$`))).toBe(1)
    }
    expect(await textCount(ui, /^Sessions folder$/)).toBe(1)
    expect(await textCount(ui, /^~\/\.claude\/sessions$/)).toBe(1)
    expect(await labelOf(ui, 'change:paths.backups_dir')).toBe('Change…')
    expect(await labelOf(ui, 'apply')).toBe('Apply to this machine…')
    const reset = (await ui.find({ key: 'reset-setting' }))?.props.options as Choice[]
    expect(reset[0]?.value).toBe('__none__')
    expect(reset.find(choice => choice.value === 'tools.claude')?.label).toBe('Tools: Claude Code')
    expect(await ui.find({ key: 'config-missing' })).toBeUndefined()
    await ui.unmount()
  })

  test(`${surface}: a pick runs config set at once, toasts Saved and re-reads; Custom… reveals an Input; a refusal is a callout`, AT_REPO, async ($, on) => {
    const failing = { 'config set review.adversarial codex --yes': bad("error: review.adversarial: 'codex' is not one of: auto") }
    const { w, ui, after } = await openTo($, on, surface, { canned: failing }, 'settings')
    const valueOf = async (key: string) => (await ui.find({ key: `set:${key}` }))?.props.value

    // the installer will answer the re-read with the new value
    w.answer('config list --json', json({ ...CONFIG, tools: { claude: 'off', codex: 'auto' } }))
    let from = w.calls.length
    await ui.select({ key: 'set:tools.claude', value: 'off' })
    expect(after(from)).toEqual(['config set tools.claude off --yes', 'config list --json', 'config path'])
    expect(w.toasts).toContain('Saved Claude Code')
    expect(await valueOf('tools.claude')).toBe('off')

    // picking what is already set writes nothing
    from = w.calls.length
    await ui.select({ key: 'set:tools.claude', value: 'off' })
    expect(after(from)).toEqual([])

    from = w.calls.length
    await ui.select({ key: 'set:guardrails.context_budget_tokens', value: '150000' })
    await ui.select({ key: 'set:guardrails.never_delete', value: 'off' })
    expect(after(from).filter(command => command.startsWith('config set'))).toEqual([
      'config set guardrails.context_budget_tokens 150000 --yes',
      'config set guardrails.never_delete off --yes',
    ])

    // the default vault goes first and the others stay; None empties the list
    from = w.calls.length
    await ui.select({ key: 'set:paths.obsidian_vaults', value: '/vaults/work' })
    await ui.select({ key: 'set:paths.obsidian_vaults', value: '__none__' })
    expect(after(from).filter(command => command.startsWith('config set'))).toEqual([
      'config set paths.obsidian_vaults /vaults/work,/vaults/notes --yes',
      'config set paths.obsidian_vaults  --yes',
    ])

    // Custom… shows a field; Enter writes what was typed, Cancel closes it
    await ui.select({ key: 'set:subagents.claude.heavy', value: '__custom__' })
    expect(await valueOf('subagents.claude.heavy')).toBe('__custom__')
    expect(await ui.find({ key: 'custom-input:subagents.claude.heavy' })).toBeDefined()
    from = w.calls.length
    await ui.input({ key: 'custom-input:subagents.claude.heavy', text: 'claude-opus-9' })
    expect(after(from)[0]).toBe('config set subagents.claude.heavy claude-opus-9 --yes')
    expect(await ui.find({ key: 'custom-input:subagents.claude.heavy' })).toBeUndefined()

    await ui.select({ key: 'set:subagents.claude.light', value: '__custom__' })
    await ui.press({ key: 'custom-cancel:subagents.claude.light' })
    expect(await ui.find({ key: 'custom-input:subagents.claude.light' })).toBeUndefined()

    // a folder is changed through its own field, prefilled with the current value
    await ui.press({ key: 'change:paths.sessions_dir' })
    expect((await ui.find({ key: 'custom-input:paths.sessions_dir' }))?.props.value).toBe('~/.claude/sessions')
    from = w.calls.length
    await ui.input({ key: 'custom-input:paths.sessions_dir', text: '/tmp/sessions' })
    expect(after(from)[0]).toBe('config set paths.sessions_dir /tmp/sessions --yes')

    // a save the installer refuses is a red callout, a re-read does not follow, and no Saved toast
    from = w.calls.length
    await ui.select({ key: 'set:review.adversarial', value: 'codex' })
    expect(after(from)).toEqual(['config set review.adversarial codex --yes'])
    expect((await ui.find({ key: 'callout:Something went wrong' }))?.props.borderColor).toBe('error')
    expect(await textCount(ui, /^Save Adversarial reviewer failed: error: review\.adversarial/)).toBe(1)
    expect(w.toasts.filter(line => line.startsWith('Saved'))).not.toContain('Saved Adversarial reviewer')
    await ui.unmount()
  })

  test(`${surface}: without config.json a callout offers the defaults; Apply and Reset ask first`, AT_REPO, async ($, on) => {
    const { w, ui, after } = await openTo($, on, surface, { hasConfig: false })

    expect(await labelOf(ui, 'overview-setup')).toBe('Set up this machine')
    expect(await textCount(ui, exact(`${isDesktop(surface) ? '' : '• '}No config.json yet: settings use the defaults`))).toBe(1)
    await ui.press({ key: 'overview-setup' })
    expect(await textCount(ui, /^No config\.json yet$/)).toBe(1)
    expect(await labelOf(ui, 'create-config')).toBe('Create it with defaults')
    expect((await ui.find({ key: 'config-missing' }))?.props.borderColor).toBe('warning')

    let from = w.calls.length
    await ui.press({ key: 'create-config' })
    expect(after(from).slice(0, 2)).toEqual(['config set editor nano --yes', 'config reset editor --yes'])
    expect(w.toasts).toContain('Saved config.json with the defaults')

    // Apply: a card first, then the job with its output in a card
    from = w.calls.length
    await ui.press({ key: 'apply' })
    expect(after(from)).toEqual([])
    expect(await textCount(ui, /^Apply this configuration to the machine\?$/)).toBe(1)
    await ui.press({ key: 'confirm-yes' })
    expect(after(from)[0]).toBe('apply --yes')
    expect(await textCount(ui, /^Apply output$/)).toBe(1)
    expect(await textCount(ui, /^Done\.$/)).toBe(1)
    await ui.press({ key: 'close-apply' })
    expect(await textCount(ui, /^Apply output$/)).toBe(0)

    // Reset: pick a setting, then a card; Cancel changes nothing
    from = w.calls.length
    await ui.select({ key: 'reset-setting', value: 'tools.claude' })
    expect(await textCount(ui, /^Reset Claude Code to its default\?$/)).toBe(1)
    await ui.press({ key: 'confirm-no' })
    expect(after(from)).toEqual([])
    await ui.select({ key: 'reset-setting', value: 'tools.claude' })
    await ui.press({ key: 'confirm-yes' })
    expect(after(from)[0]).toBe('config reset tools.claude --yes')
    await ui.unmount()
  })
}
