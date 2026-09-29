import type { Norm } from './types'

/** How far outside the user's corridor a value is, in corridor-widths, signed so that positive
 *  is the good side: above the corridor is good when higher is better, below it when lower is. */
export function deviation(value: number, norm: Norm): number {
  const span = norm.hi - norm.lo
  let z = 0
  if (value < norm.lo) z = (value - norm.lo) / span
  else if (value > norm.hi) z = (value - norm.hi) / span
  return z * norm.better
}

/** The heat-table class of a cell: `g1`/`g2` a little/a lot better than the norm, `b1`/`b2` worse,
 *  nothing inside the corridor. A quarter of a corridor-width out is where "a little" ends. */
export function toneCell(value: number, norm: Norm): '' | 'g1' | 'g2' | 'b1' | 'b2' {
  const z = deviation(value, norm)
  if (z === 0) return ''
  const strength = Math.abs(z) > 0.25 ? 2 : 1
  return `${z > 0 ? 'g' : 'b'}${strength}` as 'g1' | 'g2' | 'b1' | 'b2'
}

/** Outside the corridor on the worse side — the value that is printed in the alarm colour. */
export function isWorse(value: number, norm: Norm): boolean {
  return deviation(value, norm) < 0
}
