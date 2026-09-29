import { Fragment } from 'react'

/** A ready phrase from the server with a few words picked out — `["Weight ", {strong: "86.1"}, " kg"]`.
 *  `nw` keeps a range or a date from breaking across lines. Plain data, no markup: nothing the
 *  server sends is ever parsed as HTML. */
export type RichText = ReadonlyArray<string | { strong: string } | { nw: string }>

export function RichTextView({ parts }: { parts: RichText }) {
  return (
    <>
      {parts.map((part, i) => {
        if (typeof part === 'string') return <Fragment key={i}>{part}</Fragment>
        if ('strong' in part) return <b key={i}>{part.strong}</b>
        return (
          <span key={i} className="nw">
            {part.nw}
          </span>
        )
      })}
    </>
  )
}
