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

const LAST_LANG = 'vitals-lang'

/** The language this device last opened in. A visit with nothing cached starts that dictionary
 *  while the session is still on its way, instead of only once it has answered. */
export function lastLanguage(): Lang | null {
  try {
    const value = localStorage.getItem(LAST_LANG)
    return value === 'ru' || value === 'en' ? value : null
  } catch {
    return null
  }
}

export function rememberLanguage(lang: Lang): void {
  try {
    localStorage.setItem(LAST_LANG, lang)
  } catch {
    /* nowhere to keep it: the next cold visit just waits for the session */
  }
}

/** Start fetching a dictionary without waiting for it. Modules load once, so the later
 *  `loadDictionary()` picks up the same request; a failure here is left for that call to see. */
export function preloadDictionary(lang: Lang): void {
  loaders[lang]().catch(() => undefined)
}
