import { createFileRoute } from '@tanstack/react-router'
import { TodayPlaceholder } from '@/features/today/TodayPlaceholder'

export const Route = createFileRoute('/today')({
  component: TodayPlaceholder,
})
