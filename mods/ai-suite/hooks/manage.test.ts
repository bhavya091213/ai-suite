// Run with: claude plugin test mods/ai-suite
// Installed, Updates, Workflows and Doctor on both surfaces: cards, badges, link dots, filters,
// the confirm card before Retire / Pull / Update / Push, file lists and previews.
import { expect, test } from 'claude-code/testing'
import { AT_REPO, SURFACES, badgeText, buttonKeys, exact, isActive, isDesktop, labelOf, openTo, textCount } from './testkit'

for (const surface of SURFACES) {
  test(`${surface}: Installed shows state badges, link dots and the buttons each card needs, and filters`, AT_REPO, async ($, on) => {
    const { ui } = await openTo($, on, surface, {}, 'installed')

    expect(await labelOf(ui, 'installed-filter:tool-managed')).toBe('Tool-managed')
    expect(await isActive(ui, 'All')).toBe(true)
    const badge = (text: string) => exact(badgeText(surface, text))
    expect(await textCount(ui, badge('✓ installed'))).toBe(2)
    expect(await textCount(ui, badge('≠ modified'))).toBe(1)
    expect(await textCount(ui, badge('? foreign'))).toBe(1)
    expect(await textCount(ui, badge('⚙ tool-managed'))).toBe(1)
    expect(await textCount(ui, badge('! problem'))).toBe(2)
    expect(await textCount(ui, exact(isDesktop(surface) ? 'shared' : '[shared]'))).toBe(2)
    expect(await textCount(ui, /^alpha skill$/)).toBe(1)
    expect(await textCount(ui, /^! claude: real directory shadows the shared skill$/)).toBe(1)
    // the desktop colours its badges by the theme: installed green, modified amber, foreign Claude's, problem red
    if (isDesktop(surface)) {
      const colour = async (text: string) => (await ui.find({ type: 'Text', text: badge(text) }))?.props.color
      expect([await colour('✓ installed'), await colour('≠ modified'), await colour('? foreign'), await colour('! problem')]).toEqual([
        'success',
        'warning',
        'claude',
        'error',
      ])
    }

    // claude ● codex ● on shared cards: green ok, red broken (the desktop's status strip adds one red ● for the issues)
    const dots = await ui.findAll({ type: 'Text', text: /^●$/ })
    expect(dots.filter(dot => dot.props.color === 'success')).toHaveLength(3)
    expect(dots.filter(dot => dot.props.color === 'error')).toHaveLength(isDesktop(surface) ? 2 : 1)

    const keys = await buttonKeys(ui)
    for (const wanted of ['update:shared/beta', 'relink:shared/beta', 'retire:shared/alpha', 'files:shared/beta', 'retire:claude/ghost']) {
      expect(keys).toContain(wanted)
    }
    for (const unwanted of ['update:shared/alpha', 'relink:shared/alpha', 'retire:claude/learned', 'files:claude/learned']) {
      expect(keys).not.toContain(unwanted)
    }
    expect(await labelOf(ui, 'retire:shared/alpha')).toBe('Retire…')

    const cards = async () =>
      (await ui.findAll({ type: 'Box' })).map(box => box.key ?? '').filter(key => key.startsWith('card:'))
    expect(await cards()).toEqual(['card:shared/alpha', 'card:shared/beta', 'card:claude/gamma', 'card:claude/ghost', 'card:claude/learned'])
    const narrowed = [
      ['problems', ['card:shared/beta', 'card:claude/ghost']],
      ['foreign', ['card:claude/ghost']],
      ['tool-managed', ['card:claude/learned']],
      ['modified', ['card:shared/beta']],
    ] as const
    for (const [filter, expected] of narrowed) {
      await ui.press({ key: `installed-filter:${filter}` })
      expect(await cards()).toEqual(expected)
    }
    await ui.unmount()
  })

  test(`${surface}: Installed runs Update and Relink, lists Files, and asks before Retire`, AT_REPO, async ($, on) => {
    const { w, ui, after } = await openTo($, on, surface, {}, 'installed')
    let from = w.calls.length

    await ui.press({ key: 'files:shared/beta' })
    expect(after(from)).toEqual(['tree beta --scope shared'])
    expect(await textCount(ui, /^└── SKILL\.md$/)).toBe(1)
    expect(await labelOf(ui, 'files:shared/beta')).toBe('Hide files')
    await ui.press({ key: 'files:shared/beta' })
    expect(await textCount(ui, /^└── SKILL\.md$/)).toBe(0)

    from = w.calls.length
    await ui.press({ key: 'update:shared/beta' })
    await ui.press({ key: 'relink:shared/beta' })
    expect(after(from).filter(command => /^(update |relink )/.test(command))).toEqual([
      'update beta --scope shared --yes',
      'relink beta --yes',
    ])

    from = w.calls.length
    await ui.press({ key: 'retire:claude/ghost' })
    expect(after(from)).toEqual([])
    expect(await textCount(ui, /^Retire claude\/ghost\?$/)).toBe(1)
    expect(await textCount(ui, /^Its files move to ~\/\.agents\/backups; nothing is deleted\.$/)).toBe(1)
    expect(await labelOf(ui, 'confirm-yes')).toBe('Yes, retire')
    await ui.press({ key: 'view-overview' })
    expect(await labelOf(ui, 'retire:claude/ghost')).toBe('Retire…')
    await ui.press({ key: 'confirm-yes' })
    expect(after(from)[0]).toBe('retire ghost --scope claude --yes')
    expect(await textCount(ui, /^Retired claude\/ghost \(moved to a backup\)\.$/)).toBe(1)
    await ui.unmount()
  })

  test(`${surface}: Updates shows the git card, the commits and the changed skills; Pull and Update ask first`, AT_REPO, async ($, on) => {
    const { w, ui, after } = await openTo($, on, surface, {}, 'updates')

    expect(await textCount(ui, /^3 commits behind origin\/main$/)).toBe(1)
    expect(await textCount(ui, /^branch main · upstream origin\/main · ahead 0 · behind 3 · last fetch 20/)).toBe(1)
    expect(await textCount(ui, /^abc1234$/)).toBe(1)
    expect(await textCount(ui, /^feat: one$/)).toBe(1)
    expect(await textCount(ui, /^1 file changed upstream$/)).toBe(1)
    expect(await labelOf(ui, 'pull')).toBe('Pull 3 commits…')
    expect(await labelOf(ui, 'update:shared/beta')).toBe('Update beta')
    expect(await labelOf(ui, 'update-changed')).toBe('Update 1 changed skill…')

    let from = w.calls.length
    await ui.press({ key: 'fetch' })
    expect(after(from)).toEqual(['updates --json --fetch'])
    expect(w.toasts).toContain('Fetched')

    from = w.calls.length
    await ui.press({ key: 'pull' })
    expect(after(from)).toEqual([])
    expect(await textCount(ui, /^Pull 3 commits from upstream\?$/)).toBe(1)
    await ui.press({ key: 'confirm-yes' })
    expect(after(from)[0]).toBe('pull --yes')

    from = w.calls.length
    await ui.press({ key: 'update-changed' })
    expect(after(from)).toEqual([])
    expect(await textCount(ui, /^Update 1 changed skill\?$/)).toBe(1)
    expect(await labelOf(ui, 'confirm-yes')).toBe('Yes, update 1')
    await ui.press({ key: 'confirm-yes' })
    expect(after(from)[0]).toBe('update beta --scope shared --yes')

    from = w.calls.length
    await ui.press({ key: 'update:shared/beta' })
    expect(after(from)[0]).toBe('update beta --scope shared --yes')
    await ui.unmount()
  })

  test(`${surface}: Workflows has cards with a SKILL.md preview and Retire / Push ask first; Doctor draws rows and tools`, AT_REPO, async ($, on) => {
    const { w, ui, after } = await openTo($, on, surface, {}, 'workflows')

    expect(await textCount(ui, exact(badgeText(surface, '✓ valid')))).toBe(1)
    expect(await textCount(ui, exact(badgeText(surface, '! invalid')))).toBe(1)
    expect(await textCount(ui, /^3 phases · 5 skills$/)).toBe(1)
    expect(await textCount(ui, /^2 phases · 1 skill · phase 2 names a skill that is not installed$/)).toBe(1)
    expect(await textCount(ui, /^Create or edit workflows with \.\/install\.sh \(tab 0\)$/)).toBe(1)
    expect(await labelOf(ui, 'preview:ship')).toBe('Preview SKILL.md')
    expect(await labelOf(ui, 'workflow-push:ship')).toBe('Push to repo…')

    let from = w.calls.length
    await ui.press({ key: 'preview:ship' })
    expect(after(from)).toEqual(['workflow render ship'])
    expect(await textCount(ui, /^line 1 of the workflow$/)).toBe(1)
    expect(await textCount(ui, /^Showing 1-12 of 23$/)).toBe(1)
    await ui.press({ key: 'next:preview' })
    expect(await textCount(ui, /^Showing 13-23 of 23$/)).toBe(1)
    expect(await textCount(ui, /^line 20 of the workflow$/)).toBe(1)
    expect(await labelOf(ui, 'preview:ship')).toBe('Hide preview')

    from = w.calls.length
    await ui.press({ key: 'workflow-push:ship' })
    expect(await textCount(ui, /^Copy workflow ship into the repo\?$/)).toBe(1)
    await ui.press({ key: 'confirm-no' })
    await ui.press({ key: 'workflow-retire:ship' })
    expect(after(from)).toEqual([])
    expect(await textCount(ui, /^Retire workflow ship\?$/)).toBe(1)
    await ui.press({ key: 'confirm-yes' })
    expect(after(from)[0]).toBe('workflow retire ship --yes')

    // Doctor: coloured check rows, then the tools as two columns
    await ui.press({ key: 'view-doctor' })
    expect(await textCount(ui, /^no blockers · 1 warning$/)).toBe(1)
    expect((await ui.find({ type: 'Text', text: '✓' }))?.props.color).toBe('success')
    expect((await ui.find({ type: 'Text', text: '!' }))?.props.color).toBe('warning')
    expect(await textCount(ui, /^python$/)).toBe(1)
    expect(await textCount(ui, /^not a checkout$/)).toBe(1)
    expect(await textCount(ui, /^2\.1\.0 \(Claude Code\)$/)).toBe(1)
    expect(await textCount(ui, /^not found$/)).toBe(1)
    from = w.calls.length
    await ui.press({ key: 'refresh' })
    expect(after(from)).toEqual(['doctor --json', 'caps --json'])
    await ui.unmount()
  })
}
