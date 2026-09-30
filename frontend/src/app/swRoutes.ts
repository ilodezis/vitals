import { SCREEN_PATH } from '@/components/shell/nav'

const escapePattern = (path: string): string => path.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** The addresses the service worker answers with the app shell when offline or installed: the
 *  screens' own paths and a night's page under Recovery. Anything else on the site (the doctor's
 *  report, a report download, the login form) is the server's and goes to the network. */
export const APP_NAVIGATIONS: RegExp[] = [
  new RegExp(`^(?:${Object.values(SCREEN_PATH).map(escapePattern).join('|')})/?$`),
  /^\/recovery\/sleep\/[^/]+\/?$/,
]
