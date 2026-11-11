import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { Claim, ClaimStatus, ReviewTask, ReviewTaskPriority, ReviewTaskStatus } from '../types'

interface Props {
  projectId: string | null
  claims: Claim[]
  activeClaimId: string | null
  onSelectClaim: (id: string) => void
  onRefresh?: () => void
  onAuditChange?: () => void
  onError: (message: string) => void
  loading?: boolean
}

type Filter = 'all' | ClaimStatus

const FILTER_ORDER: Filter[] = ['all', 'needs_review', 'blocked', 'verified', 'approved', 'rejected', 'draft']

const STATUS_LABEL: Record<ClaimStatus, string> = {
  draft: '草稿',
  verified: '已校验',
  needs_review: '待复核',
  blocked: '已阻断',
  approved: '已采纳',
  rejected: '已拒绝',
}

const TASK_STATUS_LABEL: Record<ReviewTaskStatus, string> = {
  open: '待处理',
  in_review: '复核中',
  resolved: '已解决',
  dismissed: '已忽略',
}

const PRIORITY_LABEL: Record<ReviewTaskPriority, string> = {
  low: '低',
  normal: '普通',
  high: '高',
}

/**
 * Claim 审核台（V2 Phase-1）：全量 claim 列表 + 状态过滤 + 选中联动 evidence/viewer。
 * 数据源 GET /api/claims（含 citations）。点击某条 claim → 选中，右侧/下方 evidence panel 显示其 citation 明细并可操作。
 */
export function ReviewPanel({ projectId, claims, activeClaimId, onSelectClaim, onRefresh, onAuditChange, onError, loading }: Props) {
  const [filter, setFilter] = useState<Filter>('all')
  const [tasks, setTasks] = useState<ReviewTask[]>([])
  const [tasksLoading, setTasksLoading] = useState(false)
  const [assignee, setAssignee] = useState('')
  const [priority, setPriority] = useState<ReviewTaskPriority>('normal')
  const [comment, setComment] = useState('')
  const [busyTask, setBusyTask] = useState(false)

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: claims.length }
    for (const claim of claims) c[claim.status] = (c[claim.status] ?? 0) + 1
    return c
  }, [claims])

  const visible = useMemo(
    () => (filter === 'all' ? claims : claims.filter((c) => c.status === filter)),
    [claims, filter],
  )
  const activeTask = useMemo(
    () => tasks.find((task) => task.claim_id === activeClaimId && ['open', 'in_review'].includes(task.status)) ?? null,
    [tasks, activeClaimId],
  )

  useEffect(() => {
    loadTasks().catch((err) => onError(errMsg(err)))
  }, [projectId])

  async function loadTasks() {
    if (!projectId) {
      setTasks([])
      return
    }
    setTasksLoading(true)
    try {
      setTasks(await api.listReviewTasks(projectId))
    } finally {
      setTasksLoading(false)
    }
  }

  async function createTask() {
    if (!projectId || !activeClaimId) return
    setBusyTask(true)
    try {
      const task = await api.createReviewTask(projectId, activeClaimId, assignee.trim() || undefined, priority)
      upsertTask(task)
      await loadTasks()
      onAuditChange?.()
    } catch (err) {
      onError(errMsg(err))
    } finally {
      setBusyTask(false)
    }
  }

  async function updateTask(taskId: string, update: { status?: ReviewTaskStatus; assignee?: string; priority?: ReviewTaskPriority }) {
    if (!projectId) return
    setBusyTask(true)
    try {
      const task = await api.updateReviewTask(projectId, taskId, update)
      upsertTask(task)
      await loadTasks()
      onAuditChange?.()
    } catch (err) {
      onError(errMsg(err))
    } finally {
      setBusyTask(false)
    }
  }

  async function addComment(taskId: string) {
    if (!projectId || !comment.trim()) return
    setBusyTask(true)
    try {
      const task = await api.addReviewComment(projectId, taskId, assignee.trim() || 'reviewer', comment.trim())
      setComment('')
      upsertTask(task)
      await loadTasks()
      onAuditChange?.()
    } catch (err) {
      onError(errMsg(err))
    } finally {
      setBusyTask(false)
    }
  }

  function upsertTask(task: ReviewTask) {
    setTasks((current) => [task, ...current.filter((item) => item.id !== task.id)])
  }

  return (
    <div className="panel review-panel">
      <div className="review-toolbar">
        <span className="review-count">{claims.length} 条 claim</span>
        {onRefresh && (
          <button className="review-refresh" onClick={onRefresh} disabled={loading}>
            {loading ? '刷新中' : '刷新'}
          </button>
        )}
      </div>

      <div className="review-task-strip">
        <span>{tasks.filter((task) => ['open', 'in_review'].includes(task.status)).length} 个活跃任务</span>
        <button type="button" onClick={() => loadTasks().catch((err) => onError(errMsg(err)))} disabled={!projectId || tasksLoading}>
          {tasksLoading ? '同步中' : '同步任务'}
        </button>
      </div>

      <div className="review-filters">
        {FILTER_ORDER.filter((f) => f === 'all' || counts[f]).map((f) => (
          <button
            key={f}
            className={`review-chip${filter === f ? ' active' : ''}${f !== 'all' ? ` chip-${f}` : ''}`}
            onClick={() => setFilter(f)}
          >
            {f === 'all' ? '全部' : STATUS_LABEL[f]} <span className="chip-count">{counts[f] ?? 0}</span>
          </button>
        ))}
      </div>

      <div className="review-list">
        {visible.length === 0 && (
          <div className="muted small">{claims.length === 0 ? '暂无 claim（先生成 memo）' : '该状态下没有 claim'}</div>
        )}
        {visible.map((claim) => {
          const degraded = isDegraded(claim)
          const failed = claim.citations.filter((c) => !c.verified).length
          return (
            <button
              key={claim.id}
              className={`review-item${claim.id === activeClaimId ? ' active' : ''}`}
              onClick={() => onSelectClaim(claim.id)}
            >
              <div className="review-item-head">
                <span className={`claim-status status-${claim.status}`}>{STATUS_LABEL[claim.status]}</span>
                <span className="review-cite-count">
                  {claim.citations.length} 引用{failed > 0 ? ` · ${failed} 失败` : ''}
                </span>
                {degraded && <span className="degraded-badge" title="引用指向的资料已被删除，需重新取证">🗑 资料已删</span>}
              </div>
              <div className="review-item-text">{claim.text}</div>
            </button>
          )
        })}
      </div>

      {activeClaimId && (
        <div className="review-task-card">
          <div className="review-task-title">复核任务</div>
          <div className="review-task-controls">
            <input
              value={assignee}
              onChange={(event) => setAssignee(event.target.value)}
              placeholder="负责人"
              disabled={!projectId || busyTask}
            />
            <select value={priority} onChange={(event) => setPriority(event.target.value as ReviewTaskPriority)} disabled={!projectId || busyTask}>
              <option value="normal">普通</option>
              <option value="high">高</option>
              <option value="low">低</option>
            </select>
            <button type="button" onClick={createTask} disabled={!projectId || busyTask}>
              {activeTask ? '更新任务' : '创建任务'}
            </button>
          </div>
          {activeTask ? (
            <div className="review-task-detail">
              <div className="review-task-meta">
                <span>{TASK_STATUS_LABEL[activeTask.status]}</span>
                <span>{PRIORITY_LABEL[activeTask.priority]}</span>
                {activeTask.assignee && <span>{activeTask.assignee}</span>}
                <span>{activeTask.comment_count} 评论</span>
              </div>
              <div className="review-task-actions">
                <button type="button" onClick={() => updateTask(activeTask.id, { status: 'in_review' })} disabled={busyTask || activeTask.status === 'in_review'}>
                  开始复核
                </button>
                <button type="button" onClick={() => updateTask(activeTask.id, { status: 'resolved' })} disabled={busyTask}>
                  解决
                </button>
                <button type="button" onClick={() => updateTask(activeTask.id, { status: 'dismissed' })} disabled={busyTask}>
                  忽略
                </button>
              </div>
              <textarea
                value={comment}
                onChange={(event) => setComment(event.target.value)}
                placeholder="补充复核意见"
                rows={2}
                disabled={busyTask}
              />
              <button type="button" className="review-comment-btn" onClick={() => addComment(activeTask.id)} disabled={busyTask || !comment.trim()}>
                添加评论
              </button>
              {activeTask.comments?.slice(-2).map((item) => (
                <div key={item.id} className="review-comment">
                  <strong>{item.author}</strong>
                  <span>{item.body}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="muted small">当前 claim 还没有活跃复核任务。</div>
          )}
        </div>
      )}
    </div>
  )
}

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

/** 被删文档降级：claim 有 citation 因 chunk 不存在而失败（资料删除后引用悬空） */
function isDegraded(claim: Claim): boolean {
  return claim.citations.some((c) => c.failure_reason === 'chunk_not_found')
}
