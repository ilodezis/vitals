/** US Navy body fat percentage formula for male & female. */
export function computeNavyFatPct(
  waistCm: number,
  neckCm: number,
  heightCm: number,
  sex = 'male',
  hipsCm?: number,
): number | null {
  if (heightCm <= 0 || waistCm <= 0 || neckCm <= 0) return null

  if (sex === 'female') {
    if (!hipsCm || hipsCm <= 0) return null
    const inner = waistCm + hipsCm - neckCm
    if (inner <= 0) return null
    const denom = 1.29579 - 0.35004 * Math.log10(inner) + 0.221 * Math.log10(heightCm)
    if (denom <= 0) return null
    return Math.round((495.0 / denom - 450.0) * 10) / 10
  } else {
    const inner = waistCm - neckCm
    if (inner <= 0) return null
    const denom = 1.0324 - 0.19077 * Math.log10(inner) + 0.15456 * Math.log10(heightCm)
    if (denom <= 0) return null
    return Math.round((495.0 / denom - 450.0) * 10) / 10
  }
}
