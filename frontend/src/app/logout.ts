import { persister } from './persist'
import { queryClient } from './queryClient'

/** End the session: the server forgets the cookie, the device forgets what it was told, and the
 *  login form takes over. A failed request still lands on the login form — a cookie the server
 *  kept asks for it again on the next screen anyway. */
export async function logOut(): Promise<void> {
  try {
    // `manual`: the answer is a redirect to the login page, which this call does not need to read.
    await fetch('/logout', { method: 'POST', credentials: 'same-origin', redirect: 'manual' })
  } catch {
    /* offline: the local copy still goes */
  }
  queryClient.clear()
  await persister.removeClient()
  location.replace('/login')
}
