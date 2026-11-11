import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { WorkflowStatus, WorkflowStepStatus } from '../types'

interface Props {
  projectId: string | null
  /** 变化时重新拉取（导入/解析/生成/复核/删除后由 App bump） */
  refreshKey?: number
  onError?: (message: string) => void
}

const STATUS_LABEL: Record<WorkflowStepStatus, string> = {
  not_started: '未开始',
  ready: '可开始',
  in_progress: '进行中',
  needs_review: '待复核',
  blocked: '受阻',
  complete: '完成',
}

/**
 * 工作流状态条（V2 Phase-1 ③）：项目流水线步骤指示，让用户知道"下一步该做什么"。
 * 数据源 GET /api/workflow/status（后端从现有 DB/文件派生），后端是真相源；本组件只渲染。
 */
export function WorkflowPanel({ projectId, refreshKey, onError }: Props) {
  const [status, setStatus] = useState<WorkflowStatus | null>(null)

  useEffect(() => {
    if (!projectId) {
      setStatus(null)
      return
    }
    let cancelled = false
    api
      .workflowStatus(projectId)
      .then((s) => {
        if (!cancelled) setStatus(s)
      })
      .catch((e) => onError?.(e instanceof Error ? e.message : String(e)))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, refreshKey])

  if (!projectId || !status) return null

  const nextActions = status.next_actions ?? []
  const blockers = status.blockers ?? []

  return (
    <div className="workflow">
      <div className="workflow-bar" role="list" aria-label="工作流状态">
        {status.steps.map((step, index) => (
          <div className="workflow-step" role="listitem" key={step.key}>
            {index > 0 && <span className={`workflow-conn s-${step.status}`} aria-hidden />}
            <span
              className={`workflow-dot s-${step.status}`}
              title={`${step.label} · ${STATUS_LABEL[step.status]}${step.detail ? ` — ${step.detail}` : ''}`}
            >
              {step.status === 'complete' ? '✓' : step.status === 'blocked' ? '!' : index + 1}
            </span>
            <span className="workflow-label" title={step.detail}>
              {step.label}
            </span>
          </div>
        ))}
      </div>

      {(nextActions.length > 0 || blockers.length > 0) && (
        <div className="workflow-summary">
          {nextActions.length > 0 && (
            <span className="workflow-next">
              下一步：
              {nextActions.map((a) => (
                <span className="workflow-next-chip" key={a.key} title={`步骤：${a.step}`}>
                  {a.label}
                </span>
              ))}
            </span>
          )}
          {blockers.map((b) => (
            <span className="workflow-blocker" key={b.key} title={String(b.severity)}>
              ⛔ {b.message}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
