import { useMemo, useState } from 'react'
import { api } from '../api/client'
import type { AnalysisFinding, AnalysisObservation, AnalysisScanResponse } from '../types'

type ScanKey = 'red_flags' | 'financial' | 'contract'

interface Props {
  projectId: string | null
  onError: (message: string) => void
  onAuditChange?: () => void
}

const scans: Array<{ key: ScanKey; label: string; description: string }> = [
  { key: 'red_flags', label: '风险', description: '客户集中、流失、违约、亏损等信号' },
  { key: 'financial', label: '财务', description: '同指标/同期间的数值冲突' },
  { key: 'contract', label: '合同', description: '关键条款跨文件版本差异' },
]

export function AnalysisPanel({ projectId, onError, onAuditChange }: Props) {
  const [activeScan, setActiveScan] = useState<ScanKey>('red_flags')
  const [limit, setLimit] = useState(20)
  const [running, setRunning] = useState<ScanKey | null>(null)
  const [results, setResults] = useState<Partial<Record<ScanKey, AnalysisScanResponse>>>({})

  const result = results[activeScan]
  const totalFindings = useMemo(
    () => Object.values(results).reduce((sum, item) => sum + (item?.findings.length ?? 0), 0),
    [results],
  )

  async function runScan(key: ScanKey) {
    if (!projectId) return
    setRunning(key)
    setActiveScan(key)
    try {
      const response =
        key === 'red_flags'
          ? await api.scanRedFlags(projectId, limit)
          : key === 'financial'
            ? await api.scanFinancialConsistency(projectId, limit)
            : await api.scanContractClauses(projectId, limit)
      setResults((prev) => ({ ...prev, [key]: response }))
      onAuditChange?.()
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error))
    } finally {
      setRunning(null)
    }
  }

  async function runAll() {
    for (const scan of scans) {
      await runScan(scan.key)
    }
  }

  return (
    <div className="panel analysis-panel">
      <div className="analysis-head">
        <div>
          <div className="analysis-title">V2.1 分析扫描</div>
          <div className="analysis-subtitle">只生成复核信号，不绕过 citation gate</div>
        </div>
        <label className="analysis-limit">
          <span>上限</span>
          <input
            type="number"
            min={1}
            max={100}
            value={limit}
            onChange={(event) => setLimit(clampLimit(Number(event.target.value)))}
          />
        </label>
      </div>

      <div className="analysis-tabs">
        {scans.map((scan) => (
          <button
            key={scan.key}
            className={scan.key === activeScan ? 'active' : ''}
            onClick={() => setActiveScan(scan.key)}
          >
            {scan.label}
            {results[scan.key] && <span>{results[scan.key]?.findings.length ?? 0}</span>}
          </button>
        ))}
      </div>

      <div className="analysis-actions">
        {scans.map((scan) => (
          <button key={scan.key} onClick={() => runScan(scan.key)} disabled={!projectId || running !== null}>
            {running === scan.key ? '扫描中' : `扫描${scan.label}`}
          </button>
        ))}
        <button className="secondary" onClick={runAll} disabled={!projectId || running !== null}>
          全部扫描
        </button>
      </div>

      <div className="analysis-hint">
        {scans.find((scan) => scan.key === activeScan)?.description}
        {totalFindings > 0 && <span> · 已发现 {totalFindings} 条待复核信号</span>}
      </div>

      {!result && <div className="analysis-empty">选择一种扫描开始。结果会写入 run artifacts 和 audit log。</div>}

      {result && (
        <div className="analysis-results">
          <div className="analysis-run">
            <span>{result.run_id}</span>
            {result.run_dir && <code title={result.run_dir}>{shortPath(result.run_dir)}</code>}
          </div>
          {result.findings.length === 0 ? (
            <div className="analysis-empty">没有发现需要复核的冲突或风险信号。</div>
          ) : (
            result.findings.map((finding) => <FindingCard key={finding.id} finding={finding} />)
          )}
          {result.observations?.length ? (
            <details className="analysis-observations">
              <summary>查看 {result.observations.length} 条普通观察</summary>
              <ObservationList observations={result.observations.slice(0, 8)} />
            </details>
          ) : null}
        </div>
      )}
    </div>
  )
}

function FindingCard({ finding }: { finding: AnalysisFinding }) {
  return (
    <div className={`analysis-finding severity-${severityClass(finding.severity)}`}>
      <div className="finding-top">
        <span className="finding-severity">{severityLabel(finding.severity)}</span>
        <span className="finding-category">{findingTitle(finding)}</span>
      </div>
      <div className="finding-reason">{finding.reason}</div>
      {finding.values?.length ? <div className="finding-values">{finding.values.join(' / ')}</div> : null}
      {finding.variants?.length ? <div className="finding-values">{finding.variants.join(' / ')}</div> : null}
      {finding.quote && <blockquote>{finding.quote}</blockquote>}
      {finding.source_uri && <code className="finding-source">{finding.source_uri}</code>}
      {finding.observations?.length ? <ObservationList observations={finding.observations} /> : null}
    </div>
  )
}

function ObservationList({ observations }: { observations: AnalysisObservation[] }) {
  return (
    <div className="observation-list">
      {observations.map((observation, index) => (
        <div className="observation-item" key={observation.id ?? `${observation.chunk_id}-${index}`}>
          <div className="observation-meta">
            <span>{observation.metric ?? observation.clause_type ?? 'source'}</span>
            {(observation.period || observation.variant || observation.value_text) && (
              <em>{[observation.period, observation.variant, observation.value_text].filter(Boolean).join(' · ')}</em>
            )}
          </div>
          <blockquote>{observation.quote}</blockquote>
          <code>{observation.source_uri}</code>
        </div>
      ))}
    </div>
  )
}

function findingTitle(finding: AnalysisFinding): string {
  if (finding.metric) return `${finding.metric} · ${finding.period ?? 'unspecified'}`
  if (finding.clause_type) return finding.clause_type
  return finding.category
}

function severityClass(value: string): string {
  return ['high', 'medium', 'low'].includes(value) ? value : 'unknown'
}

function severityLabel(value: string): string {
  const labels: Record<string, string> = { high: '高', medium: '中', low: '低' }
  return labels[value] ?? value
}

function clampLimit(value: number): number {
  if (!Number.isFinite(value)) return 20
  return Math.max(1, Math.min(100, Math.round(value)))
}

function shortPath(path: string): string {
  const parts = path.split('/')
  return parts.slice(-3).join('/')
}
