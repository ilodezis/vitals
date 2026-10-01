import { createFileRoute } from '@tanstack/react-router'
import { openScreen } from '@/components/shell/screens'
import { moreQuery } from '@/features/more/useMoreView'

// The screen itself is drawn by the stage; the route holds the address and has its code and its data
// ready before the navigation commits, so the motion never starts on an empty screen.
export const Route = createFileRoute('/more')({
  loader: async ({ context }) => {
    await openScreen('more', context.queryClient.ensureQueryData(moreQuery))
  },
})
