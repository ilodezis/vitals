import type { components } from '@/api/schema'

/** What `GET /api/v1/today` hands the screen: values, not phrases. Numbers are numbers and dates
 *  ISO strings; the screen phrases them in the reader's language. The narrative, the messages of
 *  alerts and the owner's own words (an event's title) are the only sentences that arrive ready. */
type Schemas = components['schemas']

export type TodayView = Schemas['TodayView']
export type TodayFigure = Schemas['TodayFigure']
export type WeekChange = Schemas['WeekChange']
export type FeedRow = Schemas['FeedRow']
export type AttentionItem = Schemas['AttentionItem']
export type Goal = Schemas['Goal']
export type GoalForecast = Schemas['GoalForecast']
export type Corridor = Schemas['Corridor']
export type SyncStamp = Schemas['SyncStamp']
