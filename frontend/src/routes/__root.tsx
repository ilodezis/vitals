import type { QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, Navigate, Outlet } from '@tanstack/react-router'

export type RouterContext = {
  queryClient: QueryClient
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: Outlet,
  // Screens not built yet, or a stale link: land on Today, as the old UI's root does.
  notFoundComponent: () => <Navigate to="/today" replace />,
})
