import { createFileRoute } from '@tanstack/react-router'
import { openScreen } from '@/components/shell/screens'
import { recoveryQuery } from '@/features/recovery/useRecoveryView'

// The screen itself is drawn by the stage; the route holds the address and has its code and its data
// ready before the navigation commits, so the motion never starts on an empty screen.
export const Route = createFileRoute('/recovery')({
  loader: async ({ context }) => {
    await openScreen('recovery', context.queryClient.ensureQueryData(recoveryQuery))
  },
})
