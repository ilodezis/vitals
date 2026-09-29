import { QueryClient } from '@tanstack/react-query'

// One client for the app's lifetime: the router's loaders and the screens share
// the same cache.
export const queryClient = new QueryClient()
