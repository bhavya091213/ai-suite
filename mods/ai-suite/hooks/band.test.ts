// Run with: claude plugin test mods/ai-suite
// Visible without a command: the pane that opens at session start, and the band above the prompt.
import { expect, test } from 'claude-code/testing'
import { readSettings } from './cli'
import {
  AT_REPO,
  SURFACES,
  bad,
  flush,
  labelOf,
  mountBand,
  textCount,
  world,
  BAND,
} from './testkit'
import type { WorldOptions } from './testkit'
import type { On } from 'claude-code'

const START = { cwd: '/work', surface: 'terminal', isInteractive: true } as const
const SUMMARY = /^Skills · 3\/4 installed · 1 update · 2 issues$/

/** Another mod's band, drawn beneath ours in the chain: its row must survive. */
function otherBand(on: On): void {
  on('ui.render', { component: 'AbovePrompt' }, ($, e) =>
    $.ui.resolve(e).Text({ children: 'another mod band' }),
  )
}

/** The usual world, plus something beneath the plugin that answers the band (as the engine does). */
function band(on: On, options: WorldOptions = {}) {
  const w = world(on, options)
  otherBand(on)
  return w
}

// ------------------------------------------------------------- auto-open

test('openOnStart defaults to true and is read from the user config', () => {
  expect(readSettings({}).openOnStart).toBe(true)
  expect(readSettings({ openOnStart: true }).openOnStart).toBe(true)
  expect(readSettings({ openOnStart: false }).openOnStart).toBe(false)
})

test('session.start opens the Skills pane without focus when openOnStart is true', AT_REPO, async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await flush(w.clock)

  expect(w.openArgs).toEqual([{ id: 'ai-suite', title: 'Skills' }])
  expect(w.openArgs[0]?.focus).toBeUndefined()
  // the start check still runs alongside it
  expect(w.commands()).toEqual(['status --json', 'updates --json'])
})

test('session.start opens nothing when openOnStart is false', { options: { repoPath: '/work/ai-suite', openOnStart: false } }, async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await flush(w.clock)

  expect(w.openArgs).toHaveLength(0)
  expect(w.registered).toContain('skills')
  expect(w.statuses).toContain('skills 3/4 · 1 update · 2 issues')
})

// -------------------------------------------------------------------- band

for (const surface of SURFACES) {
  test(`${surface}: the band shows the summary, Open and Hide, above another mod's band`, AT_REPO, async ($, on) => {
    const w = band(on)
    await $.session.start(START)
    await flush(w.clock)
    const ui = await mountBand($, surface)

    expect(await textCount(ui, SUMMARY)).toBe(1)
    expect(await textCount(ui, /^another mod band$/)).toBe(1)
    expect(await labelOf(ui, 'band-open')).toBe('Open')
    expect(await labelOf(ui, 'band-hide')).toBe('Hide')
    expect((await ui.find({ key: 'band-open' }))?.props.hotkey).toBe('k')
    expect(await textCount(ui, /widen the window/)).toBe(0)
    await ui.unmount()
  })

  test(`${surface}: before the check lands the band says checking, and a failed check says why`, AT_REPO, async ($, on) => {
    const w = band(on, { canned: { 'status --json': bad('error: boom', 1) } })
    const early = await mountBand($, surface)
    expect(await textCount(early, /^Skills · checking…$/)).toBe(1)
    await early.unmount()

    await $.session.start(START)
    await flush(w.clock)
    const ui = await mountBand($, surface)
    expect(await textCount(ui, /^Skills · check failed: error: boom$/)).toBe(1)
    await ui.unmount()
  })

  test(`${surface}: Hide removes our row for the session and keeps the other band`, AT_REPO, async ($, on) => {
    const w = band(on)
    await $.session.start(START)
    await flush(w.clock)
    const ui = await mountBand($, surface)
    expect(await textCount(ui, SUMMARY)).toBe(1)

    await ui.press({ key: 'band-hide' })
    expect(await textCount(ui, SUMMARY)).toBe(0)
    expect(await labelOf(ui, 'band-open')).toBeUndefined()
    expect(await textCount(ui, /^another mod band$/)).toBe(1)
    await ui.unmount()

    // hidden is session state: a fresh drawing stays hidden
    const again = await mountBand($, surface)
    expect(await textCount(again, SUMMARY)).toBe(0)
    await again.unmount()
  })

  test(`${surface}: Open opens the pane with the keyboard`, AT_REPO, async ($, on) => {
    const w = band(on)
    await $.session.start(START)
    await flush(w.clock)
    const ui = await mountBand($, surface)

    await ui.press({ key: 'band-open' })
    expect(w.openArgs.at(-1)).toEqual({ id: 'ai-suite', title: 'Skills', focus: true, closeOnEscape: true })
    await ui.unmount()
  })

  test(`${surface}: a pane left waiting on a narrow terminal is explained, and Open seats it`, AT_REPO, async ($, on) => {
    const w = band(on, { placed: false })
    await $.session.start(START)
    await flush(w.clock)
    const ui = await mountBand($, surface)
    expect(await textCount(ui, /^The Skills pane is waiting: widen the window or press Open\.$/)).toBe(1)

    w.setPlaced(true)
    await ui.press({ key: 'band-open' })
    expect(await textCount(ui, /widen the window/)).toBe(0)
    await ui.unmount()
  })

  test(`${surface}: the band yields to a survey`, AT_REPO, async ($, on) => {
    const w = band(on)
    await $.session.start(START)
    await flush(w.clock)
    const survey = await mountBand($, surface, { ...BAND, hasSurvey: true })
    expect(await textCount(survey, SUMMARY)).toBe(0)
    expect(await textCount(survey, /^another mod band$/)).toBe(1)
    await survey.unmount()
  })
}

test('with no repo and no summary the band draws nothing of its own', AT_REPO, async ($, on) => {
  const w = band(on, { hasRepo: false })
  await $.session.start(START)
  await flush(w.clock)
  const ui = await mountBand($, 'terminal')

  expect(await textCount(ui, /^Skills/)).toBe(0)
  expect(await labelOf(ui, 'band-open')).toBeUndefined()
  expect(await textCount(ui, /^another mod band$/)).toBe(1)
  await ui.unmount()
})
