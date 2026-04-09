import { useState, useRef, useEffect, useCallback } from 'react'
import type { Project, WaveformLayerConfig, TextLayerConfig } from '../types'
import { api } from '../api/client'

interface Props { project: Project; onRefresh: () => void }

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'
function storageUrl(p: string): string {
  if (!p) return ''; const r = p.replace(/\\/g, '/').split('storage/')[1]; return r ? `${API_BASE}/storage/${r}` : ''
}

const FONTS = [
  { value: 'Pretendard, sans-serif', label: 'Pretendard' },
  { value: 'Arial, sans-serif', label: 'Arial' },
  { value: '"Noto Sans KR", sans-serif', label: 'Noto Sans KR' },
  { value: '"Noto Serif KR", serif', label: 'Noto Serif (명조)' },
  { value: 'Georgia, serif', label: 'Georgia' },
  { value: '"Courier New", monospace', label: 'Courier New' },
  { value: '"Times New Roman", serif', label: 'Times New Roman' },
  { value: 'Impact, sans-serif', label: 'Impact' },
  { value: '"Segoe UI", sans-serif', label: 'Segoe UI' },
  { value: '"Malgun Gothic", sans-serif', label: '맑은 고딕' },
]

const DEF: WaveformLayerConfig = {
  enabled: true, style: 'bar', color: '#FFFFFF', opacity: 0.8,
  position_x: 0.5, position_y: 0.7,
  bar_count: 60, bar_width: 4, bar_gap: 2, bar_height: 120, bar_min: 0.1,
  bar_align: 'bottom', scale: 1.0, circle_radius: 0.12,
}
const CW = 768, CH = 432, S = CW / 1920 // 캔버스 스케일

function mg(s: Partial<WaveformLayerConfig> | null): WaveformLayerConfig { return { ...DEF, ...(s || {}) } }

export default function LayerPreview({ project, onRefresh }: Props) {
  const [saving, setSaving] = useState(false)
  const layers = project.layers || { background_video: null, waveform_layer: null, text_layers: [] }
  const [wf, setWf] = useState<WaveformLayerConfig>(mg(layers.waveform_layer))
  const [texts, setTexts] = useState<TextLayerConfig[]>(
    (layers.text_layers || []).map(t => ({ ...t, font_family: t.font_family || FONTS[0].value }))
  )
  const [newText, setNewText] = useState('')
  const [addingText, setAddingText] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [playing, setPlaying] = useState(false)

  // 드래그 상태
  type DragMode = 'move-wf' | 'move-text' | 'resize-wf'
  const [dragMode, setDragMode] = useState<DragMode | null>(null)
  const [dragId, setDragId] = useState<string | null>(null)
  const [resizeCorner, setResizeCorner] = useState<string | null>(null)
  const dragStartRef = useRef<{ x: number; y: number; wf: WaveformLayerConfig } | null>(null)

  const boxRef = useRef<HTMLDivElement>(null)
  const cvRef = useRef<HTMLCanvasElement>(null)
  const animRef = useRef(0)
  const barsRef = useRef<number[]>([])
  const targRef = useRef<number[]>([])
  const tickRef = useRef(0)

  const bgUrl = storageUrl(project.images?.background || project.images?.thumbnail || '')

  // ── 파형 크기 계산 (px, 캔버스 기준) ──
  const wfNaturalW = wf.bar_count * ((wf.bar_width + wf.bar_gap) * S)
  const wfNaturalH = wf.bar_height * S
  const wfW = wfNaturalW * wf.scale
  const wfH = wfNaturalH * wf.scale
  const wfLeft = wf.position_x * CW - wfW / 2
  const wfTop = wf.position_y * CH - wfH / 2

  // ── 파형 그리기 ──
  const draw = useCallback(() => {
    const cv = cvRef.current
    if (!cv || !wf.enabled) return
    const ctx = cv.getContext('2d')
    if (!ctx) return
    cv.width = CW; cv.height = CH
    ctx.clearRect(0, 0, CW, CH)

    const count = wf.bar_count || 60
    const sc = wf.scale * S
    const bw = wf.bar_width * sc
    const gap = wf.bar_gap * sc
    const maxH = wf.bar_height * sc
    const cx = wf.position_x * CW
    const cy = wf.position_y * CH
    const totalW = count * (bw + gap)
    const startX = cx - totalW / 2

    ctx.globalAlpha = wf.opacity
    ctx.fillStyle = wf.color

    if (barsRef.current.length !== count) {
      barsRef.current = Array.from({ length: count }, () => Math.random())
      targRef.current = Array.from({ length: count }, () => Math.random())
    }
    for (let i = 0; i < count; i++)
      barsRef.current[i] += (targRef.current[i] - barsRef.current[i]) * 0.08
    const bmin = wf.bar_min ?? 0.1
    tickRef.current++
    if (tickRef.current % 6 === 0)
      for (let i = 0; i < count; i++) targRef.current[i] = Math.random() * (1 - bmin) + bmin

    if (wf.style === 'circle') {
      const r = CH * (wf.circle_radius || 0.12) * wf.scale
      const cbw = Math.max(2, bw * 0.8)
      for (let i = 0; i < count; i++) {
        const h = barsRef.current[i] * maxH
        const a = (i / count) * Math.PI * 2 - Math.PI / 2
        ctx.beginPath()
        ctx.moveTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r)
        ctx.lineTo(cx + Math.cos(a) * (r + h), cy + Math.sin(a) * (r + h))
        ctx.lineWidth = cbw; ctx.lineCap = 'round'; ctx.strokeStyle = wf.color; ctx.stroke()
      }
    } else {
      for (let i = 0; i < count; i++) {
        const h = barsRef.current[i] * maxH
        const x = startX + i * (bw + gap)
        if (wf.bar_align === 'center') ctx.fillRect(x, cy - h / 2, bw, h)
        else if (wf.bar_align === 'top') ctx.fillRect(x, cy, bw, h)
        else ctx.fillRect(x, cy - h, bw, h)
      }
    }
    ctx.globalAlpha = 1
  }, [wf])

  useEffect(() => {
    if (!playing) { draw(); return }
    let on = true
    const tick = () => { if (!on) return; draw(); animRef.current = requestAnimationFrame(tick) }
    tick()
    return () => { on = false; cancelAnimationFrame(animRef.current) }
  }, [playing, draw])
  useEffect(() => { draw() }, [draw])

  // ── 드래그 핸들러 ──
  const startDrag = (mode: DragMode, id: string, corner?: string) => (e: React.MouseEvent) => {
    e.preventDefault(); e.stopPropagation()
    setDragMode(mode); setDragId(id); setResizeCorner(corner || null)
    if (boxRef.current) {
      const r = boxRef.current.getBoundingClientRect()
      dragStartRef.current = { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height, wf: { ...wf } }
    }
  }

  const onMove = useCallback((e: React.MouseEvent) => {
    if (!dragMode || !boxRef.current || !dragStartRef.current) return
    const r = boxRef.current.getBoundingClientRect()
    const mx = (e.clientX - r.left) / r.width
    const my = (e.clientY - r.top) / r.height

    if (dragMode === 'move-wf') {
      setWf(w => ({ ...w, position_x: Math.max(0, Math.min(1, mx)), position_y: Math.max(0, Math.min(1, my)) }))
    } else if (dragMode === 'move-text') {
      setTexts(prev => prev.map(t => t.id === dragId ? { ...t, position_x: Math.max(0, Math.min(1, mx)), position_y: Math.max(0, Math.min(1, my)) } : t))
    } else if (dragMode === 'resize-wf') {
      const start = dragStartRef.current
      const dx = Math.abs(mx - start.wf.position_x) * 2
      const dy = Math.abs(my - start.wf.position_y) * 2
      // 스케일 계산: 드래그 거리 기반
      const origW = (start.wf.bar_count * (start.wf.bar_width + start.wf.bar_gap) * S) / CW
      const origH = (start.wf.bar_height * S) / CH
      const sx = origW > 0 ? dx / origW : 1
      const sy = origH > 0 ? dy / origH : 1
      const newScale = Math.max(0.2, Math.min(5, Math.max(sx, sy)))
      setWf(w => ({ ...w, scale: Math.round(newScale * 20) / 20 }))
    }
  }, [dragMode, dragId])

  const onUp = () => { setDragMode(null); setDragId(null); setResizeCorner(null); dragStartRef.current = null }

  // ── 저장/텍스트 ──
  const save = async () => {
    setSaving(true)
    try { await api.layers.update(project.id, { ...layers, waveform_layer: wf, text_layers: texts }); await onRefresh() }
    finally { setSaving(false) }
  }
  const addTxt = async () => {
    if (!newText.trim()) return; setAddingText(true)
    try {
      await api.layers.addText(project.id, { text: newText.trim(), font_size: 36, font_family: FONTS[0].value, color: '#FFFFFF', position_x: 0.5, position_y: 0.1, bold: true })
      setNewText(''); await onRefresh()
      const u = await api.layers.get(project.id)
      setTexts((u.text_layers || []).map(t => ({ ...t, font_family: t.font_family || FONTS[0].value })))
    } finally { setAddingText(false) }
  }
  const delTxt = async (id: string) => { await api.layers.deleteText(project.id, id); setTexts(p => p.filter(t => t.id !== id)); await onRefresh() }
  const updTxt = (id: string, u: Partial<TextLayerConfig>) => setTexts(p => p.map(t => t.id === id ? { ...t, ...u } : t))

  const Sl = ({ label, value, min, max, step, fmt, onChange }: {
    label: string; value: number; min: number; max: number; step: number; fmt?: (v: number) => string; onChange: (v: number) => void
  }) => (
    <div>
      <div className="flex justify-between text-[10px] text-gray-500 mb-0.5">
        <span>{label}</span><span>{fmt ? fmt(value) : value}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(parseFloat(e.target.value))} className="w-full accent-purple-600 h-1" />
    </div>
  )

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold text-white">🎬 레이어 설정</h2>
        <div className="flex gap-2">
          <button onClick={() => setPlaying(p => !p)}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${playing ? 'bg-red-700 hover:bg-red-600 text-white' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'}`}>
            {playing ? '⏸ 정지' : '▶ 미리보기'}</button>
          <button onClick={save} disabled={saving}
            className="bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white px-4 py-1.5 rounded-lg text-xs font-semibold">
            {saving ? '저장 중...' : '💾 저장'}</button>
        </div>
      </div>

      {/* ── 캔버스 ── */}
      <div ref={boxRef} className="relative rounded-xl overflow-hidden border border-gray-800 mb-5 select-none mx-auto"
        style={{ width: CW, height: CH, background: '#000' }}
        onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp}>

        {bgUrl ? <img src={bgUrl} alt="" className="absolute inset-0 w-full h-full object-cover" draggable={false} />
          : <div className="absolute inset-0 flex items-center justify-center text-gray-700 text-sm">배경 이미지 없음</div>}

        {wf.enabled && (
          <>
            <canvas ref={cvRef} width={CW} height={CH} className="absolute inset-0 pointer-events-none" />

            {/* 파형 바운딩 박스 + 리사이즈 핸들 */}
            {wf.style !== 'circle' && (
              <div className="absolute border border-dashed border-white/20 hover:border-white/40 transition-colors"
                style={{ left: wfLeft, top: wfTop, width: wfW, height: wfH }}>
                {/* 이동 핸들 (중앙) */}
                <div className="absolute inset-0 cursor-move" onMouseDown={startDrag('move-wf', 'wf')} />
                {/* 리사이즈 핸들 (4코너) */}
                {['nw','ne','sw','se'].map(corner => (
                  <div key={corner}
                    className={`absolute w-3 h-3 bg-white/40 hover:bg-white/80 border border-white/60 rounded-sm transition-colors ${
                      corner.includes('n') ? 'top-0' : 'bottom-0'} ${corner.includes('w') ? 'left-0' : 'right-0'
                    } ${corner === 'nw' || corner === 'se' ? 'cursor-nwse-resize' : 'cursor-nesw-resize'}`}
                    style={{ transform: 'translate(-50%,-50%)' }}
                    onMouseDown={startDrag('resize-wf', 'wf', corner)} />
                ))}
              </div>
            )}

            {/* 원형: 이동 핸들만 */}
            {wf.style === 'circle' && (
              <div className="absolute w-8 h-8 cursor-move rounded-full border-2 border-white/30 hover:border-white/60 bg-white/10 flex items-center justify-center"
                style={{ left: `${wf.position_x * 100}%`, top: `${wf.position_y * 100}%`, transform: 'translate(-50%,-50%)' }}
                onMouseDown={startDrag('move-wf', 'wf')}>
                <span className="text-[8px] text-white/50">+</span>
              </div>
            )}
          </>
        )}

        {texts.map(l => (
          <div key={l.id}
            className={`absolute cursor-move ${dragId === l.id && dragMode === 'move-text' ? 'ring-2 ring-purple-400' : 'hover:ring-1 hover:ring-white/30'}`}
            style={{
              left: `${l.position_x * 100}%`, top: `${l.position_y * 100}%`, transform: 'translate(-50%,-50%)',
              fontSize: `${l.font_size * S}px`, fontFamily: l.font_family || FONTS[0].value,
              color: l.color, fontWeight: l.bold ? 'bold' : 'normal',
              textShadow: '2px 2px 4px rgba(0,0,0,0.8)', whiteSpace: 'nowrap', userSelect: 'none',
            }}
            onMouseDown={startDrag('move-text', l.id)}
            onDoubleClick={() => setEditId(editId === l.id ? null : l.id)}>
            {l.text}
          </div>
        ))}
      </div>

      {/* ── 컨트롤 ── */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">파형</h3>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={wf.enabled} onChange={e => setWf(w => ({ ...w, enabled: e.target.checked }))}
                className="w-3.5 h-3.5 accent-purple-600" />
              <span className="text-xs text-gray-500">켜기</span>
            </label>
          </div>
          {wf.enabled && (
            <div className="space-y-2.5">
              <div className="flex gap-1.5">
                {(['bar', 'line', 'circle'] as const).map(s => (
                  <button key={s} onClick={() => setWf(w => ({ ...w, style: s }))}
                    className={`flex-1 py-1.5 rounded-lg text-xs font-medium ${wf.style === s ? 'bg-purple-600 text-white' : 'bg-gray-800 text-gray-500 hover:text-gray-300'}`}>
                    {s === 'bar' ? '막대' : s === 'line' ? '라인' : '원형'}</button>))}
              </div>
              {wf.style !== 'circle' && (
                <div className="flex gap-1.5">
                  {(['bottom', 'center', 'top'] as const).map(a => (
                    <button key={a} onClick={() => setWf(w => ({ ...w, bar_align: a }))}
                      className={`flex-1 py-1 rounded-lg text-[10px] font-medium ${wf.bar_align === a ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-500 hover:text-gray-300'}`}>
                      {a === 'bottom' ? '⬇ 바닥' : a === 'center' ? '⬌ 중간' : '⬆ 위'}</button>))}
                </div>
              )}
              <div className="flex items-center gap-2">
                <input type="color" value={wf.color} onChange={e => setWf(w => ({ ...w, color: e.target.value }))}
                  className="w-7 h-7 rounded bg-gray-800 border border-gray-700 cursor-pointer" />
                <input value={wf.color} onChange={e => setWf(w => ({ ...w, color: e.target.value }))}
                  className="flex-1 bg-gray-800 text-white rounded-lg px-2 py-1 text-xs border border-gray-700 font-mono" />
              </div>
              <Sl label="전체 크기" value={wf.scale} min={0.2} max={3} step={0.1}
                fmt={v => `${Math.round(v * 100)}%`} onChange={v => setWf(w => ({ ...w, scale: v }))} />
              <Sl label="막대 개수" value={wf.bar_count} min={10} max={200} step={5}
                fmt={v => `${v}개`} onChange={v => { setWf(w => ({ ...w, bar_count: v })); barsRef.current = []; targRef.current = [] }} />
              <Sl label="막대 너비" value={wf.bar_width} min={1} max={20} step={1}
                fmt={v => `${v}px`} onChange={v => setWf(w => ({ ...w, bar_width: v }))} />
              <Sl label="막대 간격" value={wf.bar_gap} min={0} max={15} step={1}
                fmt={v => `${v}px`} onChange={v => setWf(w => ({ ...w, bar_gap: v }))} />
              <Sl label="막대 높이" value={wf.bar_height} min={20} max={400} step={10}
                fmt={v => `${v}px`} onChange={v => setWf(w => ({ ...w, bar_height: v }))} />
              <Sl label="높이 편차" value={wf.bar_min ?? 0.1} min={0} max={0.95} step={0.05}
                fmt={v => v >= 0.9 ? '균일' : v === 0 ? '큰 차이' : `${Math.round(v*100)}%`}
                onChange={v => setWf(w => ({ ...w, bar_min: v }))} />
              <Sl label="불투명도" value={wf.opacity} min={0} max={1} step={0.05}
                fmt={v => `${Math.round(v * 100)}%`} onChange={v => setWf(w => ({ ...w, opacity: v }))} />
              {wf.style === 'circle' && (
                <Sl label="원 반지름" value={wf.circle_radius} min={0.05} max={0.3} step={0.01}
                  fmt={v => `${Math.round(v * 100)}%`} onChange={v => setWf(w => ({ ...w, circle_radius: v }))} />
              )}
            </div>
          )}
        </div>

        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">텍스트</h3>
          <div className="flex gap-1.5 mb-3">
            <input value={newText} onChange={e => setNewText(e.target.value)} placeholder="텍스트 입력..."
              className="flex-1 bg-gray-800 text-white rounded-lg px-2.5 py-1.5 text-xs border border-gray-700 focus:outline-none focus:border-purple-500"
              onKeyDown={e => { if (e.key === 'Enter') addTxt() }} />
            <button onClick={addTxt} disabled={addingText || !newText.trim()}
              className="bg-purple-600 hover:bg-purple-500 disabled:opacity-40 text-white px-3 py-1.5 rounded-lg text-xs font-semibold">+</button>
          </div>
          <div className="space-y-2 max-h-52 overflow-y-auto">
            {texts.length === 0 && <div className="text-center py-4 text-gray-700 text-xs">드래그로 이동 · 더블클릭 편집</div>}
            {texts.map(l => (
              <div key={l.id} className="bg-gray-800 rounded-lg p-2.5 space-y-2">
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded shrink-0 border border-gray-600" style={{ backgroundColor: l.color }} />
                  <span className="flex-1 text-xs text-white truncate" style={{ fontFamily: l.font_family }}>{l.text}</span>
                  <button onClick={() => setEditId(editId === l.id ? null : l.id)}
                    className="text-gray-500 hover:text-gray-300 text-[10px]">{editId === l.id ? '▲' : '✏️'}</button>
                  <button onClick={() => delTxt(l.id)} className="text-gray-600 hover:text-red-400 text-[10px]">✕</button>
                </div>
                {editId === l.id && (
                  <div className="space-y-2 pt-1.5 border-t border-gray-700">
                    <input value={l.text} onChange={e => updTxt(l.id, { text: e.target.value })}
                      className="w-full bg-gray-900 text-white rounded px-2 py-1 text-xs border border-gray-700" />
                    <select value={l.font_family || FONTS[0].value} onChange={e => updTxt(l.id, { font_family: e.target.value })}
                      className="w-full bg-gray-900 text-white rounded px-2 py-1 text-xs border border-gray-700">
                      {FONTS.map(f => <option key={f.value} value={f.value} style={{ fontFamily: f.value }}>{f.label}</option>)}
                    </select>
                    <div className="flex gap-2 items-center">
                      <input type="color" value={l.color} onChange={e => updTxt(l.id, { color: e.target.value })}
                        className="w-6 h-6 rounded cursor-pointer bg-gray-900 border border-gray-700" />
                      <input type="number" value={l.font_size} onChange={e => updTxt(l.id, { font_size: parseInt(e.target.value) || 24 })}
                        className="w-14 bg-gray-900 text-white rounded px-2 py-1 text-xs border border-gray-700" min={12} max={200} />
                      <span className="text-[10px] text-gray-600">px</span>
                      <button onClick={() => updTxt(l.id, { bold: !l.bold })}
                        className={`px-2 py-0.5 rounded text-xs font-bold ${l.bold ? 'bg-purple-600 text-white' : 'bg-gray-900 text-gray-500 border border-gray-700'}`}>B</button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
      <p className="text-[10px] text-gray-700 mt-3 text-center">파형 박스: 안쪽 드래그=이동, 코너 드래그=리사이즈 · 텍스트 드래그=이동, 더블클릭=편집</p>
    </div>
  )
}
