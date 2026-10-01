import { createFileRoute } from '@tanstack/react-router'
import { openScreen } from '@/components/shell/screens'
import { shareQuery } from '@/features/share/useShareView'

// The screen itself is drawn by the stage; the route holds the address and has its code and its data
// ready before the navigation commits, so the motion never starts on an empty screen.
export const Route = createFileRoute('/share')({
  loader: async ({ context }) => {
    await openScreen('share', context.queryClient.ensureQueryData(shareQuery))
  },
})
