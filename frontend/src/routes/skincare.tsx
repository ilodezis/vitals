import { createFileRoute } from '@tanstack/react-router'
import { openScreen } from '@/components/shell/screens'
import { skincareQuery } from '@/features/skincare/useSkincareView'

// The screen itself is drawn by the stage; the route holds the address and has its code and its data
// ready before the navigation commits, so the motion never starts on an empty screen.
export const Route = createFileRoute('/skincare')({
  loader: async ({ context }) => {
    await openScreen('skincare', context.queryClient.ensureQueryData(skincareQuery))
  },
})
