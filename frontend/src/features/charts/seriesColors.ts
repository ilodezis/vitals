/** Series colours of a custom chart. Amber (`--accent`, `--warn`) stays out: it means
 *  "now / the one action" everywhere else, and a warning tone would read as an alarm. */
export const SERIES_COLORS = [
  'var(--cool)',
  'var(--violet)',
  'var(--good)',
  'var(--deep)',
  'var(--fg-2)',
  'var(--muted)',
] as const

/** The colour of a series slot; slots past the end of the palette wrap around. */
export function seriesColor(slot: number): string {
  return SERIES_COLORS[((slot % SERIES_COLORS.length) + SERIES_COLORS.length) % SERIES_COLORS.length] ?? SERIES_COLORS[0]
}
