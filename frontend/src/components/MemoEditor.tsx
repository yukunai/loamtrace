import { Fragment } from 'react'
import type { Claim } from '../types'

interface Props {
  markdown: string
  claims: Claim[]
  activeClaimId?: string | null
  onClaimClick: (claimId: string) => void
}

/**
 * 轻量 memo 渲染：把 [E:claim_id ...] 证据标记（计划书 §12.3）渲染成可点击 chip，
 * 点击联动 evidence panel + 原文高亮。不引入完整 markdown 库，按行做最小渲染。
 */
const E_MARKER = /\[E:([a-zA-Z0-9_]+)(?:\s*·\s*[^\]]+)?\]/g

export function MemoEditor({ markdown, claims, activeClaimId, onClaimClick }: Props) {
  const claimMap = new Map(claims.map((c) => [c.id, c]))
  const lines = markdown.split('\n')

  return (
    <div className="panel memo-editor">
      <div className="memo-doc">
        {lines.map((line, i) => (
          <Fragment key={i}>{renderLine(line)}</Fragment>
        ))}
      </div>
    </div>
  )

  function renderLine(line: string) {
    if (line.startsWith('# ')) return <h1 className="memo-h1">{inline(line.slice(2))}</h1>
    if (line.startsWith('## ')) return <h2 className="memo-h2">{inline(line.slice(3))}</h2>
    if (line.startsWith('> ')) return <blockquote className="memo-quote">{inline(line.slice(2))}</blockquote>
    if (line.trim() === '') return <div className="memo-spacer" />
    return <p className="memo-p">{inline(line)}</p>
  }

  function inline(text: string) {
    const out: React.ReactNode[] = []
    let last = 0
    let m: RegExpExecArray | null
    E_MARKER.lastIndex = 0
    let key = 0
    while ((m = E_MARKER.exec(text)) !== null) {
      if (m.index > last) out.push(<span key={key++}>{stripDel(text.slice(last, m.index))}</span>)
      const claimId = m[1]
      const claim = claimMap.get(claimId)
      const blocked = claim?.status === 'blocked'
      const cls = [
        'evidence-chip',
        blocked ? 'blocked' : 'ok',
        claimId === activeClaimId ? 'active' : '',
      ]
        .filter(Boolean)
        .join(' ')
      out.push(
        <button
          key={key++}
          className={cls}
          onClick={() => onClaimClick(claimId)}
          title={claim ? claim.text : claimId}
        >
          {blocked ? '⛔' : '🔗'} {claimId}
        </button>,
      )
      last = m.index + m[0].length
    }
    if (last < text.length) out.push(<span key={key++}>{stripDel(text.slice(last))}</span>)
    return out
  }
}

// 渲染 ~~删除线~~（被阻断 claim 在 mock memo 中用删除线表示）
function stripDel(s: string): React.ReactNode {
  const parts = s.split(/~~(.+?)~~/g)
  if (parts.length === 1) return s
  return parts.map((p, i) =>
    i % 2 === 1 ? <del key={i}>{p}</del> : <Fragment key={i}>{p}</Fragment>,
  )
}
