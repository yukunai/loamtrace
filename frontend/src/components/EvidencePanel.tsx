import type { Citation, Claim, CitationStatus } from '../types'

interface Props {
  claim: Claim | null
  activeCitationId?: string | null
  onCitationClick: (c: Citation) => void
  onCitationAction?: (c: Citation, action: 'approve' | 'reject' | 'replace' | 'correct') => void
  onJudgeSupport?: (claim: Claim) => void
  judgingSupport?: boolean
  supportJudgeStatus?: string | null
}

/**
 * Evidence panel / citation review（计划书 §13.3）。
 * 展示选中 claim 的每条 citation：quote、来源、校验状态、失败原因，
 * 点击高亮原文，并提供 approve / reject / replace。
 */
export function EvidencePanel({
  claim,
  activeCitationId,
  onCitationClick,
  onCitationAction,
  onJudgeSupport,
  judgingSupport,
  supportJudgeStatus,
}: Props) {
  if (!claim) {
    return (
      <div className="panel evidence-panel empty">
        <p className="muted">点击 memo 中的 [E:…] 标记或搜索结果，查看证据</p>
      </div>
    )
  }

  return (
    <div className="panel evidence-panel">
      <div className="evidence-header">
        <span className={`claim-status status-${claim.status}`}>{claimStatusLabel(claim.status)}</span>
        <span className="claim-id">{claim.id}</span>
      </div>
      <div className="claim-text">{claim.text}</div>
      {onJudgeSupport && (
        <div className="support-judge-bar">
          <button
            type="button"
            onClick={() => onJudgeSupport(claim)}
            disabled={judgingSupport || !claim.citations.some((citation) => citation.verified)}
          >
            {judgingSupport ? '判断中…' : '支撑性判断'}
          </button>
          {supportJudgeStatus && <span>{supportJudgeStatus}</span>}
        </div>
      )}
      {(claim.calculation_formula || claim.source_numbers?.length) && (
        <div className="computed-claim-box">
          {claim.calculation_formula && (
            <div className="computed-row">
              <span>公式</span>
              <code>{claim.calculation_formula}</code>
            </div>
          )}
          {claim.source_numbers?.length ? (
            <div className="computed-row">
              <span>来源数字</span>
              <div className="source-number-list">
                {claim.source_numbers.map((number, index) => (
                  <code key={`${number}-${index}`}>{number}</code>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      )}
      {claim.status === 'blocked' && (
        <div className="blocked-banner">
          ⛔ 该 claim 未通过校验闸门，不会进入正式 memo / PPT（计划书 §11.5）
        </div>
      )}

      <div className="citation-list">
        {claim.citations.length === 0 && (
          <div className="error-box">该 claim 没有任何 citation —— 按规则应被阻断</div>
        )}
        {claim.citations.map((c) => (
          <div
            key={c.id}
            className={`citation-card${c.id === activeCitationId ? ' active' : ''}`}
          >
            <button className="citation-quote" onClick={() => onCitationClick(c)} title="点击在原文中高亮">
              “{c.quote}”
            </button>
            <div className="citation-meta">
              <span className={`cite-badge ${citeBadgeClass(c)}`}>{citeStatusLabel(c)}</span>
              <span className="source-uri" title={c.source_uri}>{shortUri(c.source_uri)}</span>
            </div>
            {c.failure_reason && (
              <div className="failure-reason">失败原因：{failureLabel(c.failure_reason)}</div>
            )}
            {(c.support_level || c.support_judge_label) && (
              <div className="support-signals">
                {c.support_level && (
                  <div className={`support-signal support-${supportClass(c.support_level)}`}>
                    <span>规则</span>
                    <strong>{supportLabel(c.support_level)}</strong>
                    {c.support_reason && <em>{c.support_reason}</em>}
                  </div>
                )}
                {c.support_judge_label && (
                  <div className={`support-signal support-${supportClass(c.support_judge_label)}`}>
                    <span>Judge</span>
                    <strong>{supportLabel(c.support_judge_label)}</strong>
                    {c.support_judge_reason && <em>{c.support_judge_reason}</em>}
                  </div>
                )}
              </div>
            )}
            {onCitationAction && (
              <div className="citation-actions">
                <button onClick={() => onCitationAction(c, 'approve')} disabled={c.verified}>
                  人工通过
                </button>
                <button onClick={() => onCitationAction(c, 'reject')}>拒绝</button>
                <button onClick={() => onCitationAction(c, 'replace')}>替换</button>
                <button onClick={() => onCitationAction(c, 'correct')}>纠正</button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function supportClass(value: string): string {
  return ['direct', 'partial', 'weak'].includes(value) ? value : 'unknown'
}

function supportLabel(value: string): string {
  const map: Record<string, string> = {
    direct: '直接支撑',
    partial: '部分支撑',
    weak: '支撑较弱',
  }
  return map[value] ?? value
}

function deriveStatus(c: Citation): CitationStatus {
  if (c.verified) {
    if (c.verification_method === 'manual_approved') return 'manual_approved'
    if (c.verification_method === 'fuzzy_quote_match') return 'fuzzy_verified'
    return 'verified'
  }
  if (c.failure_reason) return 'failed'
  return 'unverified'
}

function citeBadgeClass(c: Citation): string {
  return `cite-${deriveStatus(c)}`
}

function citeStatusLabel(c: Citation): string {
  const map: Record<CitationStatus, string> = {
    verified: '已校验·精确',
    fuzzy_verified: '已校验·模糊',
    failed: '校验失败',
    unverified: '未校验',
    manual_approved: '人工通过',
  }
  return map[deriveStatus(c)]
}

function claimStatusLabel(s: Claim['status']): string {
  const map: Record<Claim['status'], string> = {
    draft: '草稿',
    verified: '已校验',
    needs_review: '待复核',
    blocked: '已阻断',
    approved: '已采纳',
    rejected: '已拒绝',
  }
  return map[s]
}

function failureLabel(reason: string): string {
  const map: Record<string, string> = {
    number_not_found: '数字未在原文找到',
    number_mismatch: '数字与原文不一致',
    quote_not_found: 'quote 未在 chunk 中匹配',
    entity_not_found: 'claim 中的实体（专名/缩写）未在引用证据中出现',
    chunk_not_found: 'citation 指向的 chunk 不存在',
    manual_rejected: '人工拒绝',
    source_uri_invalid: 'source_uri 无法解析',
    source_uri_mismatch: 'citation 的 source_uri 与 chunk 来源不一致',
    ocr_low_confidence: 'OCR 置信度过低，需人工确认',
    computed_formula_missing: 'computed claim 缺少计算公式',
    computed_source_numbers_missing: 'computed claim 缺少来源数字',
  }
  return map[reason] ?? reason
}

function shortUri(uri: string): string {
  // pdf://doc_abc#page=8&chunk=chunk_123 -> doc_abc · page=8
  try {
    const [scheme, rest] = uri.split('://')
    const [docId, frag = ''] = rest.split('#')
    const page = /page=(\d+)/.exec(frag)?.[1]
    const sheet = /sheet=([^&]+)/.exec(frag)?.[1]
    const para = /paragraph=(\d+)/.exec(frag)?.[1]
    const table = /table=(\d+)/.exec(frag)?.[1]
    const heading = /heading=([^&]+)/.exec(frag)?.[1]
    const loc = page
      ? `page=${page}`
      : sheet
        ? `sheet=${decodeURIComponent(sheet)}`
        : para
          ? `¶${para}`
          : table
            ? `table=${table}`
            : heading
              ? `# ${decodeURIComponent(heading)}`
              : ''
    return `${scheme}·${docId.slice(0, 10)}${loc ? ' · ' + loc : ''}`
  } catch {
    return uri
  }
}
