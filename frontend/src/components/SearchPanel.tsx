import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Chunk, SearchOptions } from '../types'

interface Props {
  projectId: string | null
  onPick: (chunk: Chunk) => void
  onUseForReplacement?: (chunk: Chunk) => void
  activeChunkId?: string | null
  canReplace?: boolean
  onAuditChange?: () => void
}

export function SearchPanel({ projectId, onPick, onUseForReplacement, activeChunkId, canReplace, onAuditChange }: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Chunk[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [searched, setSearched] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [topN, setTopN] = useState(12)
  const [rrfK, setRrfK] = useState(60)
  const [ftsTopN, setFtsTopN] = useState(50)
  const [vectorTopN, setVectorTopN] = useState(50)
  const [keywordBoost, setKeywordBoost] = useState(1)
  const [vectorBoost, setVectorBoost] = useState(1)
  const [savingPreferences, setSavingPreferences] = useState(false)
  const [preferenceStatus, setPreferenceStatus] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    setPreferenceStatus(null)
    api.getRetrievalPreferences(projectId)
      .then((preferences) => {
        if (cancelled) return
        setTopN(preferences.top_n)
        setRrfK(preferences.rrf_k)
        setFtsTopN(preferences.fts_top_n)
        setVectorTopN(preferences.vector_top_n)
        setKeywordBoost(preferences.keyword_boost)
        setVectorBoost(preferences.vector_boost)
      })
      .catch((err) => {
        if (!cancelled) setPreferenceStatus(err instanceof Error ? err.message : String(err))
      })
    return () => {
      cancelled = true
    }
  }, [projectId])

  async function run(e?: React.FormEvent) {
    e?.preventDefault()
    if (!projectId || !query.trim()) return
    setLoading(true)
    setError(null)
    try {
      const res = await api.search(projectId, query.trim(), currentSearchOptions())
      setResults(res.results)
      setSearched(true)
      onAuditChange?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  async function savePreferences() {
    if (!projectId) return
    setSavingPreferences(true)
    setPreferenceStatus(null)
    try {
      await api.saveRetrievalPreferences(projectId, currentSearchOptions())
      setPreferenceStatus('已保存')
    } catch (err) {
      setPreferenceStatus(err instanceof Error ? err.message : String(err))
    } finally {
      setSavingPreferences(false)
    }
  }

  function currentSearchOptions(): SearchOptions {
    return searchOptions({
      topN,
      rrfK,
      ftsTopN,
      vectorTopN,
      keywordBoost,
      vectorBoost,
    })
  }

  return (
    <div className="panel search-panel">
      <form className="search-box" onSubmit={run}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="检索资料（关键词 / 语义）…"
          aria-label="检索"
        />
        <button type="submit" disabled={loading || !projectId || !query.trim()}>
          {loading ? '检索中…' : '检索'}
        </button>
      </form>
      <div className="search-options-head">
        <button
          type="button"
          className={`search-options-toggle${advancedOpen ? ' active' : ''}`}
          aria-expanded={advancedOpen}
          onClick={() => setAdvancedOpen((open) => !open)}
        >
          检索参数
        </button>
        <span className="search-options-summary">
          top {topN} · FTS {ftsTopN} · Vec {vectorTopN}
        </span>
      </div>
      {advancedOpen && (
        <div className="search-options-panel">
          <div className="search-options-grid">
            <NumberOption label="结果" value={topN} min={1} max={50} step={1} onChange={setTopN} />
            <NumberOption label="RRF k" value={rrfK} min={1} max={500} step={1} onChange={setRrfK} />
            <NumberOption label="FTS" value={ftsTopN} min={1} max={200} step={1} onChange={setFtsTopN} />
            <NumberOption label="Vector" value={vectorTopN} min={1} max={200} step={1} onChange={setVectorTopN} />
            <NumberOption label="关键词权重" value={keywordBoost} min={0} max={10} step={0.1} onChange={setKeywordBoost} />
            <NumberOption label="语义权重" value={vectorBoost} min={0} max={10} step={0.1} onChange={setVectorBoost} />
          </div>
          <div className="search-options-actions">
            <button type="button" onClick={savePreferences} disabled={!projectId || savingPreferences}>
              {savingPreferences ? '保存中…' : '保存为项目默认'}
            </button>
            {preferenceStatus && <span>{preferenceStatus}</span>}
          </div>
        </div>
      )}

      {error && <div className="error-box">检索失败：{error}</div>}

      <div className="result-list">
        {searched && !loading && results.length === 0 && (
          <div className="muted">无匹配结果</div>
        )}
        {results.map((c) => (
          <div
            key={c.id}
            className={`result-item${c.id === activeChunkId ? ' active' : ''}`}
          >
            <button className="result-main" onClick={() => onPick(c)}>
              <div className="result-meta">
                {c.heading_path && <span className="heading">{c.heading_path}</span>}
                {c.page_start != null && <span className="page">p.{c.page_start}</span>}
                {c.score != null && <span className="score">{c.score.toFixed(2)}</span>}
              </div>
              <div className="result-text">{snippet(c.text, query)}</div>
            </button>
            {canReplace && onUseForReplacement && (
              <button className="replace-evidence-btn" onClick={() => onUseForReplacement(c)}>
                替换为此证据
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function NumberOption({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
}) {
  return (
    <label className="search-option">
      <span>{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(event) => onChange(clampNumber(event.currentTarget.value, min, max, value))}
      />
    </label>
  )
}

function clampNumber(raw: string, min: number, max: number, fallback: number): number {
  const parsed = Number(raw)
  if (!Number.isFinite(parsed)) return fallback
  return Math.min(max, Math.max(min, parsed))
}

function searchOptions(values: {
  topN: number
  rrfK: number
  ftsTopN: number
  vectorTopN: number
  keywordBoost: number
  vectorBoost: number
}): SearchOptions {
  return {
    top_n: values.topN,
    rrf_k: values.rrfK,
    fts_top_n: values.ftsTopN,
    vector_top_n: values.vectorTopN,
    keyword_boost: values.keywordBoost,
    vector_boost: values.vectorBoost,
  }
}

function snippet(text: string, query: string): string {
  const q = query.trim()
  if (!q) return text.slice(0, 220)
  const i = text.toLowerCase().indexOf(q.toLowerCase())
  if (i < 0) return text.slice(0, 220)
  const start = Math.max(0, i - 60)
  return (start > 0 ? '…' : '') + text.slice(start, i + q.length + 140)
}
