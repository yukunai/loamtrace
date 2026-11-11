import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type { BBox, CitationTarget, DocumentMeta } from '../types'

export interface Highlight {
  id: string
  bbox: BBox
  /** 是否当前聚焦的高亮（更醒目 + 自动滚入视野） */
  active?: boolean
  /** 是否为校验失败/风险高亮（红色） */
  failed?: boolean
  label?: string
}

interface Props {
  doc: DocumentMeta | null
  projectId: string | null
  highlights: Highlight[]
  /** 跳转到的页码（来自 citation 点击）；变化时自动切页 */
  gotoPage?: number | null
  /** 当前引用文本 + source_uri，用于 DOCX/XLSX 等无页面渲染格式的文本视图 */
  activeQuote?: { text: string; sourceUri: string } | null
  activeTarget?: CitationTarget | null
  onManualText?: (doc: DocumentMeta, text: string) => Promise<void>
}

const FALLBACK_RATIO = 792 / 612 // letter 纵横比，无 page 元信息时兜底

export function PdfViewer({ doc, projectId, highlights, gotoPage, activeQuote, activeTarget, onManualText }: Props) {
  const pages = doc?.pages ?? []
  const [pageNumber, setPageNumber] = useState<number>(pages[0]?.page_number ?? 1)
  const [zoom, setZoom] = useState(1)
  const [renderFailed, setRenderFailed] = useState(false)
  const [manualTextOpen, setManualTextOpen] = useState(false)
  const [manualText, setManualText] = useState('')
  const [savingManualText, setSavingManualText] = useState(false)
  const activeRef = useRef<HTMLDivElement | null>(null)

  // citation 跳转 -> 切到目标页
  useEffect(() => {
    if (gotoPage && gotoPage !== pageNumber) setPageNumber(gotoPage)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gotoPage])

  // 文档切换时复位到首页
  useEffect(() => {
    setPageNumber(pages[0]?.page_number ?? 1)
    setRenderFailed(false)
    setManualTextOpen(false)
    setManualText('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc?.id])

  // 高亮变化时把 active 滚入视野
  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [highlights, pageNumber])

  const page = useMemo(
    () => pages.find((p) => p.page_number === pageNumber),
    [pages, pageNumber],
  )
  const ratio = page && page.width ? page.height / page.width : FALLBACK_RATIO

  const pageHighlights = highlights.filter((h) => h.bbox.page === pageNumber)
  const renderUrl = doc && projectId ? api.pageRenderUrl(doc.id, pageNumber, projectId) : ''
  const showImage = !api.isMock && !renderFailed && !!renderUrl

  if (!doc) {
    return (
      <div className="viewer empty">
        <p>选择一个文档查看原文与引用高亮</p>
      </div>
    )
  }

  // DOCX/XLSX 等无页面渲染、无 bbox 的格式：诚实降级为文本视图（计划书 §2.5/§13.2），
  // 不冒充 PDF 页面贴图。判定：有 pages 即按 PDF 渲染，否则按格式给文本视图。
  const isPdf =
    pages.length > 0 ||
    doc.mime_type === 'application/pdf' ||
    doc.filename.toLowerCase().endsWith('.pdf')
  if (!isPdf) {
    return <NonPdfView doc={doc} activeQuote={activeQuote} activeTarget={activeTarget} />
  }

  const pageWidth = 560 * zoom

  return (
    <div className="viewer">
      <div className="viewer-toolbar">
        <div className="doc-name" title={doc.filename}>
          {doc.filename}
          {doc.ocr_used && <span className="ocr-badge" title={ocrTitle(doc)}>OCR{ocrConfidenceLabel(doc)}</span>}
          {doc.ocr_required && <span className="ocr-required-badge" title="扫描版或无可提取文本层，需 OCR 后再作为证据使用">需OCR</span>}
          {doc.parser_version === 'manual-text-v1' && <span className="fmt-badge">人工文本</span>}
        </div>
        <div className="spacer" />
        <button onClick={() => stepPage(-1)} disabled={!canStep(-1)} aria-label="上一页">‹</button>
        <span className="page-indicator">
          第 {pageNumber} 页{pages.length ? ` / 共 ${pages.length} 页` : ''}
        </span>
        <button onClick={() => stepPage(1)} disabled={!canStep(1)} aria-label="下一页">›</button>
        <span className="divider" />
        <button onClick={() => setZoom((z) => Math.max(0.5, +(z - 0.1).toFixed(2)))} aria-label="缩小">−</button>
        <span className="zoom-indicator">{Math.round(zoom * 100)}%</span>
        <button onClick={() => setZoom((z) => Math.min(2.5, +(z + 0.1).toFixed(2)))} aria-label="放大">＋</button>
      </div>

      {doc.ocr_required && (
        <div className="ocr-required-banner">
          该 PDF 未发现可提取文本层，当前不会生成可验证引用；需 OCR 或人工补录后再进入正式 memo / PPT。
        </div>
      )}
      {(doc.ocr_required || doc.status === 'failed') && onManualText && (
        <ManualTextPanel
          open={manualTextOpen}
          text={manualText}
          saving={savingManualText}
          onToggle={() => setManualTextOpen((open) => !open)}
          onTextChange={setManualText}
          onSubmit={submitManualText}
        />
      )}

      <div className="viewer-scroll">
        <div
          className="page-canvas"
          style={{ width: pageWidth, height: pageWidth * ratio }}
        >
          {showImage ? (
            <img
              src={renderUrl}
              alt={`第 ${pageNumber} 页`}
              className="page-image"
              onError={() => setRenderFailed(true)}
              draggable={false}
            />
          ) : (
            <div className="page-placeholder">
              {api.isMock ? 'MOCK 页面（无渲染图，仅演示高亮坐标）' : '无渲染图'}
            </div>
          )}

          {/* bbox 高亮 overlay：归一化坐标 [0,1] × 实际显示尺寸（计划书 §7.2） */}
          {pageHighlights.map((h) => {
            const left = `${h.bbox.x0 * 100}%`
            const top = `${h.bbox.y0 * 100}%`
            const width = `${(h.bbox.x1 - h.bbox.x0) * 100}%`
            const height = `${(h.bbox.y1 - h.bbox.y0) * 100}%`
            const cls = [
              'bbox-highlight',
              h.active ? 'active' : '',
              h.failed ? 'failed' : '',
            ]
              .filter(Boolean)
              .join(' ')
            return (
              <div
                key={h.id}
                ref={h.active ? activeRef : undefined}
                className={cls}
                style={{ left, top, width, height }}
                title={h.label}
              />
            )
          })}
        </div>
      </div>

      {pageHighlights.length === 0 && highlights.length > 0 && (
        <div className="viewer-hint">
          当前引用在第 {highlights[0].bbox.page} 页，
          <button className="linklike" onClick={() => setPageNumber(highlights[0].bbox.page)}>
            跳转
          </button>
        </div>
      )}
    </div>
  )

  function canStep(d: number): boolean {
    if (!pages.length) return d > 0 ? pageNumber < 9999 : pageNumber > 1
    const idx = pages.findIndex((p) => p.page_number === pageNumber)
    return idx + d >= 0 && idx + d < pages.length
  }
  function stepPage(d: number) {
    if (!pages.length) {
      setPageNumber((n) => Math.max(1, n + d))
      return
    }
    const idx = pages.findIndex((p) => p.page_number === pageNumber)
    const next = pages[idx + d]
    if (next) setPageNumber(next.page_number)
  }

  async function submitManualText() {
    if (!doc || !onManualText || !manualText.trim()) return
    setSavingManualText(true)
    try {
      await onManualText(doc, manualText)
      setManualText('')
      setManualTextOpen(false)
    } finally {
      setSavingManualText(false)
    }
  }
}

function ManualTextPanel({
  open,
  text,
  saving,
  onToggle,
  onTextChange,
  onSubmit,
}: {
  open: boolean
  text: string
  saving: boolean
  onToggle: () => void
  onTextChange: (text: string) => void
  onSubmit: () => void
}) {
  return (
    <div className="manual-text-panel">
      <div className="manual-text-head">
        <span>人工补录校正文本</span>
        <button type="button" onClick={onToggle}>{open ? '收起' : '补录'}</button>
      </div>
      {open && (
        <>
          <textarea
            value={text}
            onChange={(event) => onTextChange(event.currentTarget.value)}
            placeholder="粘贴 OCR 校正文本或人工整理后的原文。保存后会重建该文档的 evidence chunk。"
            rows={5}
          />
          <div className="manual-text-actions">
            <button type="button" onClick={onSubmit} disabled={saving || !text.trim()}>
              {saving ? '保存中…' : '保存并索引'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}

/** DOCX/XLSX 等无页面渲染格式的文本视图：显示格式、来源定位与引用原文 */
function NonPdfView({
  doc,
  activeQuote,
  activeTarget,
}: {
  doc: DocumentMeta
  activeQuote?: { text: string; sourceUri: string } | null
  activeTarget?: CitationTarget | null
}) {
  const ext = doc.filename.toLowerCase().split('.').pop() || ''
  const fmt = ext === 'docx' ? 'DOCX' : ext === 'xlsx' ? 'XLSX' : ext.toUpperCase() || '文档'
  const loc = activeTarget?.location_label ?? (activeQuote ? locationLabel(activeQuote.sourceUri) : null)
  const contextText = activeTarget?.paragraph?.text ?? activeTarget?.block?.text ?? activeTarget?.chunk?.text
  const heading = activeTarget?.paragraph?.heading_path ?? activeTarget?.block?.heading_path
  const cells = activeTarget?.cells ?? []

  return (
    <div className="viewer">
      <div className="viewer-toolbar">
        <div className="doc-name" title={doc.filename}>
          {doc.filename}
          <span className="fmt-badge">{fmt}</span>
          {doc.ocr_used && <span className="ocr-badge" title={ocrTitle(doc)}>OCR{ocrConfidenceLabel(doc)}</span>}
          {doc.ocr_required && <span className="ocr-required-badge" title="需要 OCR 后再作为证据使用">需OCR</span>}
        </div>
      </div>

      <div className="nonpdf-view">
        <div className="nonpdf-note">
          {fmt} 无页面渲染图；引用以{ext === 'xlsx' ? ' 工作表 / 单元格 ' : ' 段落 / 表格 '}级定位（计划书 §2.5 诚实降级）。
        </div>
        {activeQuote ? (
          <div className="nonpdf-quote-card">
            <div className="nonpdf-target-head">
              {loc && <div className="nonpdf-loc">{loc}</div>}
              {activeTarget?.precision && <span className="nonpdf-precision">{precisionLabel(activeTarget.precision)}</span>}
            </div>
            {heading && <div className="nonpdf-heading">{heading}</div>}
            {contextText && contextText !== activeQuote.text && (
              <div className="nonpdf-context">
                <span>上下文</span>
                <p>{contextText}</p>
              </div>
            )}
            {cells.length > 0 && (
              <div className="nonpdf-cells" aria-label="引用单元格">
                {cells.map((cell) => (
                  <div className="nonpdf-cell" key={cell.id}>
                    <code>{cell.cell_ref ?? `${cell.row_index ?? '?'}:${cell.col_index ?? '?'}`}</code>
                    <span>{cell.text ?? valueLabel(cell.value)}</span>
                  </div>
                ))}
              </div>
            )}
            <blockquote className="nonpdf-quote">“{activeQuote.text}”</blockquote>
          </div>
        ) : (
          <div className="nonpdf-empty">点击证据面板的 quote 或检索结果，在此查看被引用的原文文本。</div>
        )}
      </div>
    </div>
  )
}

function ocrConfidenceLabel(doc: DocumentMeta): string {
  return typeof doc.ocr_confidence === 'number' ? ` ${Math.round(doc.ocr_confidence)}%` : ''
}

function ocrTitle(doc: DocumentMeta): string {
  const confidence = ocrConfidenceLabel(doc)
  return `OCR 来源${confidence ? `，平均置信度 ${confidence.trim()}` : ''}，精度较低时需人工复核`
}

/** 从 source_uri 解析人类可读的来源定位标签（docx 段落/表格 / xlsx 表+行/单元格 / md/html 标题） */
function locationLabel(uri: string): string | null {
  try {
    const frag = uri.split('#')[1] ?? ''
    const params = new URLSearchParams(frag)
    const sheet = params.get('sheet')
    const cell = params.get('cell')
    const row = params.get('row')
    const para = params.get('paragraph')
    const table = params.get('table')
    const heading = params.get('heading')
    if (sheet) return `工作表 ${sheet}${cell ? ` · 单元格 ${cell}` : row ? ` · 第 ${row} 行` : ''}`
    if (para) return `第 ${para} 段`
    if (table) return `第 ${table} 个表格`
    if (heading) return `标题：${heading}`
    return null
  } catch {
    return null
  }
}

function precisionLabel(precision: string): string {
  const map: Record<string, string> = {
    paragraph: '段落级',
    table: '表格级',
    cell: '单元格级',
    range: '区域级',
    row: '行级',
    block: '块级',
    document: '文档级',
  }
  return map[precision] ?? precision
}

function valueLabel(value: unknown): string {
  if (value == null) return ''
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}
