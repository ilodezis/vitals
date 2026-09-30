import type { ReactNode } from 'react'

const INLINE_RE = /`([^`]+)`|\[([^\]]+)\]\(((?:[^()]+|\([^()]*\))+)\)|\*\*([^*]+)\*\*|\*([^*]+)\*/g

function isSafeHttpUrl(raw: string): boolean {
  try {
    const parsed = new URL(raw.trim())
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}

export function renderInline(text: string): ReactNode[] {
  const out: ReactNode[] = []
  let lastIndex = 0
  let key = 0

  for (const match of text.matchAll(INLINE_RE)) {
    const idx = match.index ?? 0
    if (idx > lastIndex) {
      out.push(text.slice(lastIndex, idx))
    }

    const [full, code, linkLabel, linkUrl, bold, italic] = match
    if (code !== undefined) {
      out.push(
        <span key={key++} className="md-code">
          {code}
        </span>,
      )
    } else if (linkLabel !== undefined && linkUrl !== undefined) {
      const cleanUrl = linkUrl.trim()
      if (isSafeHttpUrl(cleanUrl)) {
        out.push(
          <a
            key={key++}
            href={cleanUrl}
            rel="noopener noreferrer"
            target="_blank"
          >
            {renderInline(linkLabel)}
          </a>,
        )
      } else {
        out.push(...renderInline(linkLabel))
      }
    } else if (bold !== undefined) {
      out.push(<strong key={key++}>{renderInline(bold)}</strong>)
    } else if (italic !== undefined) {
      out.push(<em key={key++}>{renderInline(italic)}</em>)
    } else {
      out.push(full)
    }

    lastIndex = idx + full.length
  }

  if (lastIndex < text.length) {
    out.push(text.slice(lastIndex))
  }

  return out
}

export interface MarkdownProps {
  source: string
}

export function Markdown({ source }: MarkdownProps) {
  const lines = source.split(/\r?\n/)
  const blocks: ReactNode[] = []
  let paragraph: string[] = []
  let listType: 'ul' | 'ol' | null = null
  let listItems: string[] = []
  let blockKey = 0

  const flushParagraph = () => {
    if (paragraph.length === 0) return
    const text = paragraph.join(' ')
    blocks.push(<p key={blockKey++}>{renderInline(text)}</p>)
    paragraph = []
  }

  const flushList = () => {
    if (!listType || listItems.length === 0) return
    const items = listItems.map((item, idx) => (
      <li key={idx}>{renderInline(item)}</li>
    ))
    if (listType === 'ul') {
      blocks.push(<ul key={blockKey++}>{items}</ul>)
    } else {
      blocks.push(<ol key={blockKey++}>{items}</ol>)
    }
    listType = null
    listItems = []
  }

  for (const rawLine of lines) {
    const line = rawLine.trim()
    if (!line) {
      flushParagraph()
      flushList()
      continue
    }

    const h3Match = /^###\s+(.+)$/.exec(line)
    if (h3Match?.[1]) {
      flushParagraph()
      flushList()
      blocks.push(<h5 key={blockKey++}>{renderInline(h3Match[1])}</h5>)
      continue
    }

    const h2Match = /^##\s+(.+)$/.exec(line)
    if (h2Match?.[1]) {
      flushParagraph()
      flushList()
      blocks.push(<h4 key={blockKey++}>{renderInline(h2Match[1])}</h4>)
      continue
    }

    const h1Match = /^#\s+(.+)$/.exec(line)
    if (h1Match?.[1]) {
      flushParagraph()
      flushList()
      blocks.push(<h3 key={blockKey++}>{renderInline(h1Match[1])}</h3>)
      continue
    }

    const ulMatch = /^[-*]\s+(.+)$/.exec(line)
    if (ulMatch?.[1]) {
      flushParagraph()
      if (listType && listType !== 'ul') {
        flushList()
      }
      listType = 'ul'
      listItems.push(ulMatch[1])
      continue
    }

    const olMatch = /^\d+\.\s+(.+)$/.exec(line)
    if (olMatch?.[1]) {
      flushParagraph()
      if (listType && listType !== 'ol') {
        flushList()
      }
      listType = 'ol'
      listItems.push(olMatch[1])
      continue
    }

    flushList()
    paragraph.push(line)
  }

  flushParagraph()
  flushList()

  return <>{blocks}</>
}
