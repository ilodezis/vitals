import { createFileRoute } from '@tanstack/react-router'
import { preloadScreen } from '@/components/shell/screens'
import { todayQuery } from '@/features/today/useTodayView'

// The screen itself is drawn by the stage; the route holds the address and has its code and its
// data ready before the navigation commits, so the motion never starts on an empty screen. With
// the day already on the device (even an old one) this does not wait for the network at all: the
// screen opens on it and the fresh day replaces it as it arrives.
export const Route = createFileRoute('/today')({
  loader: async ({ context }) => {
    await Promise.all([preloadScreen('today'), context.queryClient.ensureQueryData(todayQuery)])
  },
})
