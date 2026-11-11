import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { ExportPptxResponse, GenerateChartDataResponse, GenerateSlidesResponse, TableMeta } from '../types'

interface Props {
  projectId: string | null
  activeDocumentId?: string | null
  refreshKey?: number
  onError: (message: string) => void
  onAuditChange?: () => void
}

export function ChartPanel({
  projectId,
  activeDocumentId = null,
  refreshKey = 0,
  onError,
  onAuditChange,
}: Props) {
  const [tables, setTables] = useState<TableMeta[]>([])
  const [selectedTableId, setSelectedTableId] = useState('')
  const [scope, setScope] = useState<'project' | 'document'>('project')
  const [chartType, setChartType] = useState<'line' | 'bar'>('line')
  const [labelColumn, setLabelColumn] = useState(0)
  const [valueColumns, setValueColumns] = useState('')
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [decking, setDecking] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [tableDecking, setTableDecking] = useState(false)
  const [tableExporting, setTableExporting] = useState(false)
  const [result, setResult] = useState<GenerateChartDataResponse | null>(null)
  const [deckResult, setDeckResult] = useState<GenerateSlidesResponse | null>(null)
  const [exportResult, setExportResult] = useState<ExportPptxResponse | null>(null)
  const [tableDeckResult, setTableDeckResult] = useState<GenerateSlidesResponse | null>(null)
  const [tableExportResult, setTableExportResult] = useState<ExportPptxResponse | null>(null)

  const selectedTable = useMemo(
    () => tables.find((table) => table.id === selectedTableId) ?? tables[0] ?? null,
    [tables, selectedTableId],
  )
  const valueCellCount = result?.chart.data_source?.cell_ids?.length ?? 0

  useEffect(() => {
    loadTables().catch((error) => onError(error instanceof Error ? error.message : String(error)))
  }, [projectId, activeDocumentId, scope, refreshKey])

  useEffect(() => {
    if (!selectedTableId && tables[0]) setSelectedTableId(tables[0].id)
    if (selectedTableId && !tables.some((table) => table.id === selectedTableId)) {
      setSelectedTableId(tables[0]?.id ?? '')
    }
  }, [tables, selectedTableId])

  async function loadTables() {
    if (!projectId) {
      setTables([])
      return
    }
    setLoading(true)
    try {
      const listed = await api.listTables(projectId, scope === 'document' ? activeDocumentId ?? undefined : undefined)
      setTables(listed)
    } finally {
      setLoading(false)
    }
  }

  async function generate() {
    if (!projectId || !selectedTable) return
    setGenerating(true)
    try {
      const response = await api.generateChartData(
        projectId,
        selectedTable.id,
        clampColumn(labelColumn),
        parseValueColumns(valueColumns),
        chartType,
      )
      setResult(response)
      setDeckResult(null)
      setExportResult(null)
      onAuditChange?.()
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error))
    } finally {
      setGenerating(false)
    }
  }

  async function copyChartJson() {
    if (!result) return
    const text = JSON.stringify(result.chart, null, 2)
    await navigator.clipboard?.writeText(text).catch(() => undefined)
  }

  async function generateDeck() {
    if (!projectId || !result) return
    setDecking(true)
    setExportResult(null)
    try {
      const title = `${selectedTable?.caption ?? selectedTable?.sheet_name ?? 'Source'} chart`
      const response = await api.generateChartDeck(projectId, title, result.chart)
      setDeckResult(response)
      onAuditChange?.()
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error))
    } finally {
      setDecking(false)
    }
  }

  async function generateTableDeck() {
    if (!projectId || !selectedTable) return
    setTableDecking(true)
    setTableExportResult(null)
    try {
      const title = `${selectedTable.caption ?? selectedTable.sheet_name ?? 'Source'} table`
      const response = await api.generateTableDeck(projectId, selectedTable.id, title)
      setTableDeckResult(response)
      onAuditChange?.()
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error))
    } finally {
      setTableDecking(false)
    }
  }

  async function exportDeck() {
    if (!projectId || !deckResult) return
    setExporting(true)
    try {
      const response = await api.exportPptx(projectId, deckResult.deck_id)
      setExportResult(response)
      onAuditChange?.()
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error))
    } finally {
      setExporting(false)
    }
  }

  async function exportTableDeck() {
    if (!projectId || !tableDeckResult) return
    setTableExporting(true)
    try {
      const response = await api.exportPptx(projectId, tableDeckResult.deck_id)
      setTableExportResult(response)
      onAuditChange?.()
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error))
    } finally {
      setTableExporting(false)
    }
  }

  async function openExportPath(path: string, label = 'PPTX') {
    const result = await window.loamtrace?.openPath?.(path)
    if (result && !result.ok) {
      onError(`无法打开${label}：${result.error ?? path}`)
      return
    }
    if (!result) onError(`${label}位置：${path}`)
  }

  return (
    <div className="panel chart-panel">
      <div className="chart-head">
        <div>
          <div className="chart-title">V3 图表数据</div>
          <div className="chart-subtitle">从已解析表格生成带 cell_id 的 verified chart</div>
        </div>
        <button
          onClick={() => loadTables()}
          disabled={!projectId || loading || generating || decking || exporting || tableDecking || tableExporting}
        >
          {loading ? '刷新中' : '刷新表格'}
        </button>
      </div>

      <div className="chart-scope" role="group" aria-label="表格范围">
        <button className={scope === 'project' ? 'active' : ''} onClick={() => setScope('project')}>
          全项目
        </button>
        <button
          className={scope === 'document' ? 'active' : ''}
          onClick={() => setScope('document')}
          disabled={!activeDocumentId}
        >
          当前资料
        </button>
      </div>

      <label className="chart-select">
        <span>表格</span>
        <select
          value={selectedTable?.id ?? ''}
          onChange={(event) => {
            setSelectedTableId(event.target.value)
            setResult(null)
          }}
          disabled={!tables.length || generating || decking || exporting || tableDecking || tableExporting}
        >
          {tables.map((table) => (
            <option key={table.id} value={table.id}>
              {table.document_filename ?? table.document_id} · {table.caption ?? table.sheet_name ?? table.id}
            </option>
          ))}
        </select>
      </label>

      {selectedTable ? (
        <>
          <div className="chart-table-meta">
            <span>{selectedTable.row_count} rows</span>
            <span>{selectedTable.col_count} cols</span>
            <span>{selectedTable.cell_count} cells</span>
            {selectedTable.parser && <span>{selectedTable.parser}</span>}
          </div>
          <TablePreview table={selectedTable} />
        </>
      ) : (
        <div className="chart-empty">还没有可图表化的表格。导入并解析 DOCX / XLSX / PDF 表格后再刷新。</div>
      )}

      <div className="chart-controls">
        <label>
          <span>类型</span>
          <select value={chartType} onChange={(event) => setChartType(event.target.value as 'line' | 'bar')}>
            <option value="line">折线</option>
            <option value="bar">柱状</option>
          </select>
        </label>
        <label>
          <span>标签列</span>
          <input
            type="number"
            min={0}
            value={labelColumn}
            onChange={(event) => setLabelColumn(clampColumn(Number(event.target.value)))}
          />
        </label>
        <label>
          <span>数值列</span>
          <input
            value={valueColumns}
            onChange={(event) => setValueColumns(event.target.value)}
            placeholder="自动或 1,2"
            aria-label="数值列"
          />
        </label>
      </div>

      <div className="chart-actions">
        <button
          onClick={generate}
          disabled={!projectId || !selectedTable || generating || decking || exporting || tableDecking || tableExporting}
        >
          {generating ? '生成中' : '生成图表数据'}
        </button>
        <button className="secondary" onClick={copyChartJson} disabled={!result}>
          复制 JSON
        </button>
      </div>

      <div className="chart-deck-actions table-deck-actions">
        <button
          className="secondary"
          onClick={generateTableDeck}
          disabled={!projectId || !selectedTable || generating || decking || exporting || tableDecking || tableExporting}
        >
          {tableDecking ? '生成表格 Deck 中' : '生成表格 Deck'}
        </button>
        <button
          className="secondary"
          onClick={exportTableDeck}
          disabled={!tableDeckResult || generating || decking || exporting || tableDecking || tableExporting}
        >
          {tableExporting ? '导出中' : '导出表格 PPTX'}
        </button>
      </div>
      {tableDeckResult && (
        <div className="chart-export-path">
          <span>{tableDeckResult.deck.slides.length} slides</span>
          <code title={tableDeckResult.path}>{tableDeckResult.deck_id}</code>
        </div>
      )}
      {tableExportResult && (
        <div className="chart-export-path">
          <span>表格 PPTX</span>
          <code title={tableExportResult.path}>{tableExportResult.path}</code>
          <button type="button" className="open-export-btn" onClick={() => openExportPath(tableExportResult.path, '表格 PPTX')}>
            打开
          </button>
        </div>
      )}

      {result && (
        <div className="chart-result">
          <div className="chart-result-top">
            <span className="chart-verified">{result.chart.review_status ?? 'unknown'}</span>
            <span>{result.chart.chart_type}</span>
            <code title={result.run_dir}>{result.run_id}</code>
          </div>
          <div className="chart-source">
            <span>table_id</span>
            <code>{result.chart.data_source?.table_id}</code>
            <span>{valueCellCount} source cells</span>
          </div>
          <div className="chart-series-list">
            {result.chart.series?.map((series) => (
              <div className="chart-series" key={series.name}>
                <strong>{series.name}</strong>
                <div className="chart-points">
                  {series.points.map((point) => (
                    <span key={`${point.label}-${point.cell_id ?? point.value}`} title={point.cell_id}>
                      {point.label}: {point.value}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div className="chart-deck-actions">
            <button onClick={generateDeck} disabled={decking || exporting}>
              {decking ? '生成 Deck 中' : '生成图表 Deck'}
            </button>
            <button className="secondary" onClick={exportDeck} disabled={!deckResult || decking || exporting}>
              {exporting ? '导出中' : '导出图表 PPTX'}
            </button>
          </div>
          {deckResult && (
            <div className="chart-export-path">
              <span>{deckResult.deck.slides.length} slides</span>
              <code title={deckResult.path}>{deckResult.deck_id}</code>
            </div>
          )}
          {exportResult && (
            <div className="chart-export-path">
              <span>PPTX</span>
              <code title={exportResult.path}>{exportResult.path}</code>
              <button type="button" className="open-export-btn" onClick={() => openExportPath(exportResult.path, '图表 PPTX')}>
                打开
              </button>
            </div>
          )}
          <pre>{JSON.stringify(result.chart, null, 2)}</pre>
        </div>
      )}
    </div>
  )
}

function TablePreview({ table }: { table: TableMeta }) {
  return (
    <div className="chart-preview">
      {table.preview.slice(0, 4).map((row, rowIndex) => (
        <div className="chart-preview-row" key={rowIndex}>
          {row.slice(0, 5).map((cell, colIndex) => (
            <span key={`${rowIndex}-${colIndex}`} title={cell}>
              {cell || '-'}
            </span>
          ))}
        </div>
      ))}
    </div>
  )
}

function parseValueColumns(value: string): number[] | null {
  const columns = value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => Number(item))
    .filter((item) => Number.isInteger(item) && item >= 0)
  return columns.length ? Array.from(new Set(columns)) : null
}

function clampColumn(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.round(value))
}
