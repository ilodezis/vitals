import { createFileRoute } from '@tanstack/react-router'
import { openScreen } from '@/components/shell/screens'
import { geneticsQuery } from '@/features/genetics/useGeneticsView'

// The screen itself is drawn by the stage; the route holds the address and has its code and its data
// ready before the navigation commits, so the motion never starts on an empty screen.
export const Route = createFileRoute('/genetics')({
  loader: async ({ context }) => {
    await openScreen('genetics', context.queryClient.ensureQueryData(geneticsQuery))
  },
})
