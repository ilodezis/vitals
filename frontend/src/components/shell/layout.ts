import { createContext, use } from 'react'

/** The shape the layout is in. The app is one container; from 768px it is a rail beside a
 *  stage, below that a stage over a bottom bar. CSS answers this with container queries;
 *  the few things that are drawn in script (chart widths, which gestures run) ask here. */
export interface Layout {
  desktop: boolean
}

export const LayoutContext = createContext<Layout>({ desktop: false })

export const useLayout = (): Layout => use(LayoutContext)

/** The container width from which the rail replaces the bottom bar. Mirrors app.css. */
export const DESKTOP_MIN_WIDTH = 768
