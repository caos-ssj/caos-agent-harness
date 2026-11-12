import React from 'react'

/* A small, safe Markdown reader for SKILL.md: headings, lists, fenced code, paragraphs, **bold** and `code`.
   It builds React nodes and never injects HTML, so a skill body cannot run anything. */

const inline = (text: string, key: string): React.ReactNode[] => {
  const out: React.ReactNode[] = []
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g
  let last = 0
  let i = 0
  for (const m of text.matchAll(re)) {
    if (m.index! > last) out.push(text.slice(last, m.index))
    const tok = m[0]
    out.push(tok.startsWith('**') ? <strong key={`${key}-${i++}`}>{tok.slice(2, -2)}</strong> : <code key={`${key}-${i++}`}>{tok.slice(1, -1)}</code>)
    last = m.index! + tok.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

export const Markdown: React.FC<{ text: string }> = ({ text }) => {
  const lines = text.replace(/\r/g, '').split('\n')
  const nodes: React.ReactNode[] = []
  let i = 0
  let k = 0
  while (i < lines.length) {
    const ln = lines[i]
    if (/^```/.test(ln)) {
      const buf: string[] = []
      i++
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++])
      i++
      nodes.push(<pre key={k++} className="md-code">{buf.join('\n')}</pre>)
      continue
    }
    const h = /^(#{1,3})\s+(.*)$/.exec(ln)
    if (h) {
      const Tag = (`h${h[1].length + 2}` as 'h3' | 'h4' | 'h5')
      nodes.push(<Tag key={k++} className="md-h">{inline(h[2], `h${k}`)}</Tag>)
      i++
      continue
    }
    if (/^\s*[-*]\s+/.test(ln)) {
      const items: string[] = []
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*]\s+/, ''))
      nodes.push(<ul key={k++} className="md-ul">{items.map((it, j) => <li key={j}>{inline(it, `l${k}-${j}`)}</li>)}</ul>)
      continue
    }
    if (/^\s*\d+[.)]\s+/.test(ln)) {
      const items: string[] = []
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*\d+[.)]\s+/, ''))
      nodes.push(<ol key={k++} className="md-ul">{items.map((it, j) => <li key={j}>{inline(it, `o${k}-${j}`)}</li>)}</ol>)
      continue
    }
    if (!ln.trim()) { i++; continue }
    const para: string[] = [ln]
    i++
    while (i < lines.length && lines[i].trim() && !/^(```|#{1,3}\s|\s*[-*]\s|\s*\d+[.)]\s)/.test(lines[i])) para.push(lines[i++])
    nodes.push(<p key={k++} className="md-p">{inline(para.join(' '), `p${k}`)}</p>)
  }
  return <div className="md">{nodes}</div>
}
