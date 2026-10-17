// ai-suite: the skills manager inside Claude Code. A Skills pane, a status line
// entry and slash commands, all thin layers over `python -m installer`.
// The work lives in actions.ts (commands), load.ts (reads) and views.tsx (the pane).
import type { Register } from 'claude-code'
import { openPane, pressAct, runCheck, startupCheck } from './actions'
import { errText, readSettings } from './cli'
import { readPane } from './state'
import { renderPane } from './views'

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
    // Background work: not awaited, and it catches everything itself.
    if (settings.checkOnStart) void startupCheck($, settings)

    return next(e)
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
    const rows = e.props.scroll.bodyRows > 0 ? e.props.scroll.bodyRows : (e.viewport?.rows ?? 24)

    return renderPane(els, data, { rows, columns: e.props.bodyColumns }, act =>
      pressAct($, settings, act),
    )
  })
}
