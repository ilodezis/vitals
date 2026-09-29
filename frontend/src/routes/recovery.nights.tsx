import { createFileRoute } from '@tanstack/react-router'
import { preloadScreen } from '@/components/shell/screens'

// The screen itself is drawn by the stage; the route holds the address and has its code ready
// before the navigation commits, so the motion never starts on an empty screen.
export const Route = createFileRoute('/recovery/nights')({
  loader: async () => {
    await preloadScreen('nights')
  },
})
