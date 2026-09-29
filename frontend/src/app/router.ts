import { createRouter } from '@tanstack/react-router'
import { routeTree } from '@/routeTree.gen'
import { queryClient } from './queryClient'

export const router = createRouter({
  routeTree,
  // '/app' while the server-rendered UI still owns the root; '/' after the switch.
  basepath: import.meta.env.VITE_ROUTER_BASE ?? '/app',
  context: { queryClient },
  defaultPreload: 'intent',
  // Query owns freshness: loaders always run and ensureQueryData decides.
  defaultPreloadStaleTime: 0,
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
