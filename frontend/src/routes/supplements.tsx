import { createFileRoute } from '@tanstack/react-router'
import { openScreen } from '@/components/shell/screens'
import { supplementsQuery } from '@/features/supplements/useSupplementsView'

// The screen itself is drawn by the stage; the route holds the address and has its code and its data
// ready before the navigation commits, so the motion never starts on an empty screen.
export const Route = createFileRoute('/supplements')({
  loader: async ({ context }) => {
    await openScreen('supplements', context.queryClient.ensureQueryData(supplementsQuery))
  },
})
