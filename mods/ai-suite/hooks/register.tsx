// ai-suite: the skills manager inside Claude Code. A Skills pane that opens by itself at
// session start, a band above the prompt, a status line entry and slash commands, all thin
// layers over `python -m installer`. The work lives in actions.ts (commands), load.ts (reads),
// pane.tsx (the pane, with one view_*.tsx per view and the shared pieces in ui.tsx) and
// band.tsx (the band).
import type { Register } from 'claude-code'
import { autoOpenPane, openPane, pressAct, runCheck, startupCheck } from './actions'
import { renderBand } from './band'
import { errText, readSettings } from './cli'
import { readBand, readPane, setBandHidden } from './state'
import { bandText } from './summary'
import { renderPane, renderUnsupported } from './pane'

export const register: Register = (on, options) => {
  const settings = readSettings(options)

  on('session.start', async ($, e, next) => {
    // Each registration is tried alone: a refusal (a name Claude Code already
    // ships) must not stop the others.
    const attempt = async (name: string, register: () => Promise<unknown>): Promise<void> => {
      try {
        await register()
      } catch (error) {
        $.ui.log(`ai-suite: /${name} was not registered: ${errText(error)}`, { to: 'debug' })
      }
    }
    await attempt('skills', () =>
      $.command.register({
        name: 'skills',
        description: 'Open the Skills pane: install, update and repair skills',
      }),
    )
    await attempt('skills-check', () =>
      $.command.register({
        name: 'skills-check',
        description: 'Run doctor and fetch updates, then show a one-line summary',
      }),
    )
    await attempt('ai-suite', () =>
      $.command.register({
        name: 'ai-suite',
        description: 'Open the Skills pane (same as /skills)',
      }),
    )
    // The rest of the chain first, then background work: neither is awaited, both catch
    // everything themselves, and the pane opens without `focus` so it never takes the keyboard.
    const started = await next(e)
    if (settings.checkOnStart) void startupCheck($, settings)
    if (settings.openOnStart) void autoOpenPane($)

    return started
  })

  // `skills` is a name Claude Code ships; this hook answers it, and if it ever fails the
  // built-in /skills runs instead.
  on('command.run', { command: 'skills' }, async $ => ({
    text: await openPane($, settings),
  })).catch((_$, e, next) => next(e))

  on('command.run', { command: 'ai-suite' }, async $ => ({
    text: await openPane($, settings),
  }))

  on('command.run', { command: 'skills-check' }, async $ => ({
    text: await runCheck($, settings),
  }))

  on('ui.render', { component: 'Pane', requestId: 'ai-suite' }, async ($, e) => {
    const els = $.ui.resolve(e)
    const data = await readPane($)
    // The mobile app draws no text field or picker yet; it gets a one-line note instead.
    if (e.surface === 'mobile' || !('Input' in els) || !('Select' in els)) return renderUnsupported(els)

    return renderPane(els, data, e.props.bodyColumns, act => pressAct($, settings, act))
  })

  // One row above the prompt, over whatever other mods draw there. It yields to a survey,
  // stays out of the way once hidden, and draws nothing when it has nothing to say.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const below = await next(e)
    const data = await readBand($)
    const text = bandText({
      status: data.status,
      updates: data.updates,
      repoError: data.repoError,
      isChecking: settings.checkOnStart,
    })
    if (e.props.hasSurvey || data.isHidden || text === null) return below

    return renderBand(
      $.ui.resolve(e),
      { text, isPaneWaiting: data.isPaneWaiting, columns: e.props.bodyColumns },
      below,
      {
        open: async () => {
          await openPane($, settings)
        },
        hide: () => setBandHidden($, true),
      },
    )
  })
}
