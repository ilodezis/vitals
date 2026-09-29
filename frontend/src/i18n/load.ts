import type { Lang } from '@/lib/format'
import type { Dictionary } from './translate'

// One chunk per language, fetched once the session says which one is in use —
// the other never reaches the device, and neither counts toward the startup
// budget. The files are exported from vitals/i18n.py (`npm run gen:i18n`).
const loaders: Record<Lang, () => Promise<{ default: Dictionary }>> = {
  en: () => import('./en.json'),
  ru: () => import('./ru.json'),
}

export async function loadDictionary(lang: Lang): Promise<Dictionary> {
  return (await loaders[lang]()).default
}
