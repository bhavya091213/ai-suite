// The band above the prompt: one compact row with the skills summary and two
// buttons, drawn above whatever other mods put in the same band. The drawing
// is a pure function of its inputs; what a button does is handed in.
import { truncate } from './cli'
import type { Els } from './ui'

export type BandActions = {
  /** Opens the pane with the keyboard (the same as /skills). */
  open: () => Promise<void>
  /** Hides the band for the rest of the session. */
  hide: () => Promise<void>
}

export type BandView = {
  text: string
  /** True while the pane opened at session start waits undrawn. */
  isPaneWaiting: boolean
  columns: number
}

// Columns the two buttons, their hotkey label and the gaps take beside the text.
const BUTTONS_WIDTH = 28

/**
 * `below` is what the hooks beneath drew in this band (`await next(e)`); it goes under our row
 * inside a plain column Box, so another mod's band survives. That Box sets no size, position,
 * display or overflow.
 */
export function renderBand(
  els: Els,
  view: BandView,
  below: JSX.Element,
  actions: BandActions,
): JSX.Element {
  const { Box, Text, Button } = els
  const room = Math.max(12, view.columns - BUTTONS_WIDTH)
  return (
    <Box flexDirection="column">
      <Box key="ai-suite-band" flexDirection="row" gap={1}>
        <Text wrap="truncate">{truncate(view.text, room)}</Text>
        <Button key="band-open" label="Open" hotkey="k" variant="primary" onPress={actions.open} />
        <Button key="band-hide" label="Hide" onPress={actions.hide} />
      </Box>
      {view.isPaneWaiting && (
        <Text dimColor wrap="truncate">
          The Skills pane is waiting: widen the window or press Open.
        </Text>
      )}
      {below}
    </Box>
  )
}
