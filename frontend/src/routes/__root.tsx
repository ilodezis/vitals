import type { QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, Navigate } from '@tanstack/react-router'
import { sessionQuery } from '@/app/session'
import { AppShell } from '@/components/shell/AppShell'
import { loadDictionary } from '@/i18n/load'

export type RouterContext = {
  queryClient: QueryClient
}

export const Route = createRootRouteWithContext<RouterContext>()({
  // Who is signed in, and in which language, before anything draws: the shell is built from it.
  loader: async ({ context }) => {
    const session = await context.queryClient.ensureQueryData(sessionQuery)
    return { lang: session.lang, dictionary: await loadDictionary(session.lang) }
  },
  component: Root,
  // A stale link: land on Today, as the old UI's root does.
  notFoundComponent: () => <Navigate to="/today" replace />,
})

function Root() {
  const { lang, dictionary } = Route.useLoaderData()
  return <AppShell lang={lang} dictionary={dictionary} />
}
