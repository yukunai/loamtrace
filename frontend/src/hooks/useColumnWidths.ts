import { useCallback, useRef, useState } from 'react'

// 四栏布局里前三栏可调宽（侧栏 / memo / viewer），最后一栏（证据）自适应填充。
// 宽度持久化到 localStorage；分隔条双击复位。
export type ColKey = 'sidebar' | 'memo' | 'viewer'

const DEFAULTS: Record<ColKey, number> = { sidebar: 230, memo: 380, viewer: 560 }
const LIMITS: Record<ColKey, [number, number]> = {
  sidebar: [160, 460],
  memo: [260, 760],
  viewer: [320, 1100],
}
const STORE_KEY = 'loamtrace.cols.v1'

function load(): Record<ColKey, number> {
  try {
    const raw = localStorage.getItem(STORE_KEY)
    if (raw) return { ...DEFAULTS, ...JSON.parse(raw) }
  } catch {
    /* ignore */
  }
  return { ...DEFAULTS }
}

function persist(w: Record<ColKey, number>) {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(w))
  } catch {
    /* ignore */
  }
}

export function useColumnWidths(onPersist?: (widths: Record<ColKey, number>) => void) {
  const [widths, setWidths] = useState<Record<ColKey, number>>(load)
  const widthsRef = useRef(widths)
  widthsRef.current = widths
  // 拖动期间最新宽度（同步，不依赖 React 异步渲染），用于 onUp 持久化，避免存到落后一拍的值
  const pendingRef = useRef<Record<ColKey, number> | null>(null)
  const drag = useRef<{ key: ColKey; startX: number; startW: number } | null>(null)

  const onMove = useCallback((e: PointerEvent) => {
    const d = drag.current
    if (!d) return
    const [min, max] = LIMITS[d.key]
    const next = Math.max(min, Math.min(max, d.startW + (e.clientX - d.startX)))
    // 同步合并出最新宽度，不依赖 React updater 的执行时机，保证 onUp 持久化拿到的是当前值
    const base = pendingRef.current ?? widthsRef.current
    if (base[d.key] === next) return
    const nw = { ...base, [d.key]: next }
    pendingRef.current = nw
    setWidths(nw)
  }, [])

  const onUp = useCallback(() => {
    drag.current = null
    document.body.classList.remove('resizing')
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
    const latest = pendingRef.current ?? widthsRef.current
    persist(latest)
    onPersist?.(latest)
    pendingRef.current = null
  }, [onMove, onPersist])

  /** 绑定到分隔条 onPointerDown：开始拖动调整对应栏宽度 */
  const startResize = useCallback(
    (key: ColKey) => (e: React.PointerEvent) => {
      drag.current = { key, startX: e.clientX, startW: widthsRef.current[key] }
      document.body.classList.add('resizing')
      window.addEventListener('pointermove', onMove)
      window.addEventListener('pointerup', onUp)
      e.preventDefault()
    },
    [onMove, onUp],
  )

  /** 双击分隔条：该栏宽度复位为默认值 */
  const resetResize = useCallback(
    (key: ColKey) => () => {
      setWidths((prev) => {
        const next = { ...prev, [key]: DEFAULTS[key] }
        persist(next)
        onPersist?.(next)
        return next
      })
    },
    [onPersist],
  )

  const applyWidths = useCallback((next: Partial<Record<ColKey, number>>) => {
    setWidths((prev) => {
      const merged = { ...prev }
      for (const key of Object.keys(DEFAULTS) as ColKey[]) {
        const value = next[key]
        if (typeof value !== 'number') continue
        const [min, max] = LIMITS[key]
        merged[key] = Math.max(min, Math.min(max, value))
      }
      persist(merged)
      return merged
    })
  }, [])

  return { widths, startResize, resetResize, applyWidths }
}
