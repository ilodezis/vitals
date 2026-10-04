import { createFileRoute } from '@tanstack/react-router'
import { openScreen } from '@/components/shell/screens'
import { environmentLiveQuery, environmentSeriesQuery } from '@/features/environment/environmentApi'

// The screen itself is drawn by the stage; the route holds the address and has its code and its data
// ready before the navigation commits, so the motion never starts on an empty screen. The live
// reading is the one thing that must not come from a copy kept on the device: it is asked for again
// unless it is a few seconds old.
export const Route = createFileRoute('/environment')({
  loader: async ({ context }) => {
    await openScreen(
      'environment',
      context.queryClient.prefetchQuery(environmentLiveQuery),
      context.queryClient.prefetchQuery(environmentSeriesQuery(24)),
    )
  },
})
