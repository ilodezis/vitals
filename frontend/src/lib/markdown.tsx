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

function splitTableRow(line: string): string[] {
  let trimmed = line.trim()
  if (trimmed.startsWith('|')) trimmed = trimmed.slice(1)
  if (trimmed.endsWith('|')) trimmed = trimmed.slice(0, -1)
  return trimmed.split('|').map((c) => c.trim())
}

function isTableDelimiter(line: string): boolean {
  const cells = splitTableRow(line)
  return cells.length > 0 && cells.every((c) => /^:?-+:?$/.test(c))
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

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i]!
    const line = rawLine.trim()
    if (!line) {
      flushParagraph()
      flushList()
      continue
    }

    // Horizontal rule: ---, ***, ___
    if (/^(?:---|\*\*\*|___)\s*$/.test(line)) {
      flushParagraph()
      flushList()
      blocks.push(<hr key={blockKey++} />)
      continue
    }

    // Table: header line containing | followed by delimiter line
    if (line.includes('|') && i + 1 < lines.length && isTableDelimiter(lines[i + 1]!.trim())) {
      flushParagraph()
      flushList()
      const header = splitTableRow(line)
      i += 1 // Skip delimiter line
      const rows: string[][] = []
      while (i + 1 < lines.length) {
        const nextLine = lines[i + 1]!.trim()
        if (!nextLine || !nextLine.includes('|')) break
        i += 1
        const rawCells = splitTableRow(nextLine)
        const row = header.map((_, colIdx) => rawCells[colIdx] ?? '')
        rows.push(row)
      }
      blocks.push(
        <table key={blockKey++}>
          <thead>
            <tr>
              {header.map((col, cIdx) => (
                <th key={cIdx}>{renderInline(col)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rIdx) => (
              <tr key={rIdx}>
                {row.map((cell, cIdx) => (
                  <td key={cIdx}>{renderInline(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>,
      )
      continue
    }

    // Blockquote: > quote
    const quoteMatch = /^>\s*(.*)$/.exec(line)
    if (quoteMatch) {
      flushParagraph()
      flushList()
      const quoteLines = [quoteMatch[1] ?? '']
      while (i + 1 < lines.length) {
        const nextLine = lines[i + 1]!.trim()
        const nextMatch = /^>\s*(.*)$/.exec(nextLine)
        if (!nextMatch) break
        i += 1
        quoteLines.push(nextMatch[1] ?? '')
      }
      blocks.push(
        <blockquote key={blockKey++}>
          {renderInline(quoteLines.join(' '))}
        </blockquote>,
      )
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
