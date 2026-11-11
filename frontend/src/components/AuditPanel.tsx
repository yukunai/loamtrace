import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AuditEvent } from '../types'

interface Props {
  projectId: string | null
  refreshKey?: number
  onError?: (message: string) => void
}

export function AuditPanel({ projectId, refreshKey = 0, onError }: Props) {
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [loading, setLoading] = useState(false)

  async function load() {
    if (!projectId) {
      setEvents([])
      return
    }
    setLoading(true)
    try {
      setEvents(await api.listAudit(projectId, 30))
    } catch (err) {
      onError?.(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, refreshKey])

  return (
    <div className="panel audit-panel">
      <div className="audit-toolbar">
        <span>{events.length} 条最近事件</span>
        <button onClick={load} disabled={!projectId || loading}>
          {loading ? '刷新中' : '刷新'}
        </button>
      </div>
      {!projectId && <div className="slide-empty">选择项目后查看审计日志。</div>}
      {projectId && events.length === 0 && !loading && <div className="slide-empty">暂无审计事件。</div>}
      <div className="audit-list">
        {events.map((event, index) => (
          <div className="audit-item" key={event.id ?? `${event.ts}-${event.type}-${index}`}>
            <div className="audit-head">
              <span className="audit-type">{event.type}</span>
              <span className="audit-ts">{event.ts}</span>
            </div>
            <pre className="audit-payload">{formatPayload(event)}</pre>
          </div>
        ))}
      </div>
    </div>
  )
}

function formatPayload(event: AuditEvent): string {
  if (typeof event.payload_json === 'string' && event.payload_json.trim()) {
    try {
      return JSON.stringify(JSON.parse(event.payload_json), null, 2)
    } catch {
      return event.payload_json
    }
  }
  const payload = Object.fromEntries(
    Object.entries(event).filter(([key]) => !['id', 'ts', 'type', 'payload_json'].includes(key)),
  )
  return Object.keys(payload).length ? JSON.stringify(payload, null, 2) : '{}'
}
