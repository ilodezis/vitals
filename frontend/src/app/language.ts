import { persister } from './persist'
import { queryClient } from './queryClient'

/** The language was saved: everything the device kept was told in the old one (the session's
 *  language, the sentences the server wrote), and a page that reopens from that copy keeps
 *  showing it. The copy goes first, then the page starts over from the network. */
export async function restartInNewLanguage(reload: () => void = () => window.location.reload()): Promise<void> {
  queryClient.clear()
  await persister.removeClient()
  reload()
}
