import { createFileRoute } from '@tanstack/react-router'
import { openScreen } from '@/components/shell/screens'
import { glp1Query } from '@/features/glp1/useGlp1View'

// The screen itself is drawn by the stage; the route holds the address and has its code and its data
// ready before the navigation commits, so the motion never starts on an empty screen.
export const Route = createFileRoute('/glp1')({
  loader: async ({ context }) => {
    await openScreen('glp1', context.queryClient.ensureQueryData(glp1Query))
  },
})
