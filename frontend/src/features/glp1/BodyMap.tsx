import type { SiteUsage } from './sites'
import { SITE_POSITION } from './sites'

/** The body outline with a dot per injection site: the next one dashed, the last few days solid
 *  with a ring, older ones fainter the longer ago. A record and a nudge, not an order. */
export function BodyMap({ usage, label }: { usage: readonly SiteUsage[]; label: string }) {
  return (
    <svg viewBox="0 0 150 190" width={150} height={190} fill="none" stroke="#433C4D" strokeWidth={1.5} role="img" aria-label={label}>
      <circle cx={75} cy={20} r={12} />
      <path d="M52 40c6-5 14-7 23-7s17 2 23 7l12 30-8 3-9-22v44c0 4 1 8 2 12l-2 70h-12l-4-62h-4l-4 62H57l-2-70c1-4 2-8 2-12V51l-9 22-8-3z" />
      {usage.map(({ site, mark }) => {
        const [x, y] = SITE_POSITION[site]
        if (mark.kind === 'next') return <circle key={site} cx={x} cy={y} r={9} stroke="#BCA4DC" strokeDasharray="3 3" />
        if (mark.kind === 'recent') {
          return (
            <g key={site}>
              <circle cx={x} cy={y} r={7} fill="#BCA4DC" stroke="none" />
              <circle cx={x} cy={y} r={11} stroke="#BCA4DC" strokeOpacity=".35" />
            </g>
          )
        }
        return <circle key={site} cx={x} cy={y} r={5.5} fill="#BCA4DC" fillOpacity={mark.opacity} stroke="none" />
      })}
    </svg>
  )
}
