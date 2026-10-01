import { createFileRoute } from '@tanstack/react-router'
import { openScreen } from '@/components/shell/screens'
import { interactionsQuery } from '@/features/interactions/useInteractionsView'

// The screen itself is drawn by the stage; the route holds the address and has its code and its data
// ready before the navigation commits, so the motion never starts on an empty screen.
export const Route = createFileRoute('/interactions')({
  loader: async ({ context }) => {
    await openScreen('interactions', context.queryClient.ensureQueryData(interactionsQuery))
  },
})
