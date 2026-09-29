export const STEP = 0.1
export const WEIGHT_MIN = 30
export const WEIGHT_MAX = 250
export const HOLD_START = 420

/** Snap to one decimal and keep inside the range: 86.14 → 86.1, 400 → 250. */
export function clampStep(value: number, min = WEIGHT_MIN, max = WEIGHT_MAX): number {
  return Math.round(Math.min(max, Math.max(min, value)) * 10) / 10
}

/** How long to wait before the next repeat while a key is held: slow, then faster. */
export function repeatDelay(repeats: number): number {
  return repeats < 6 ? 110 : repeats < 16 ? 60 : 30
}
