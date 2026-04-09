import { useState, useRef, useEffect, useCallback } from 'react'
import type { Project, WaveformLayerConfig, TextLayerConfig } from '../types'
import { api } from '../api/client'

interface Props {
  project: Project
  onRefresh: () => void
}

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'
function storageUrl(path: string): string {
  if (!path) return ''
  const rel = path.replace(/\\/g, '/').split('storage/')[1]
  return rel ? `${API_BASE}/storage/${rel}` : ''
}

// ── 폰트 목록 ──
const FONTS = [
  { value: 'Pretendard, sans-serif', label: 'Pretendard (기본)' },
  { value: 'Arial, sans-serif', label: 'Arial' },
  { value: '"Noto Sans KR", sans-serif', label: 'Noto Sans KR' },
  { value: '"Noto Serif KR", serif', label: 'Noto Serif KR (명조)' },
  { value: 'Georgia, serif', label: 'Georgia (세리프)' },
  { value: '"Courier New", monospace', label: 'Courier New (코딩)' },
  { value: '"Times New Roman", serif', label: 'Times New Roman' },
  { value: 'Impact, sans-serif', label: 'Impact (굵은)' },
  { value: '"Segoe UI", sans-serif', label: 'Segoe UI' },
  { value: '"Malgun Gothic", sans-serif', label: '맑은 고딕' },
]

const DEFAULT_WAVEFORM: WaveformLayerConfig = {
  enabled: true,
  style: 'bar',
  color: '#FFFFFF',
  opacity: 0.8,
  position_y: 0.7,
  bar_count: 60,
  bar_width: 0.6,
  bar_height: 0.25,
  bar_align: 'bottom',
  circle_radius: 0.12,
}

const CANVAS_W = 768
const CANVAS_H = 432

function mergeWf(saved: Partial<WaveformLayerConfig> | null): WaveformLayerConfig {
  return { ...DEFAULT_WAVEFORM, ...(saved || {}) }
}

export default function LayerPreview({ project, onRefresh }: Props) {
  const [saving, setSaving] = useState(false)
  const layers = project.layers || { background_video: null, waveform_layer: null, text_layers: [] }

  const [waveform, setWaveform] = useState<WaveformLayerConfig>(mergeWf(layers.waveform_layer))
  const [textLayers, setTextLayers] = useState<TextLayerConfig[]>(
    (layers.text_layers || []).map(t => ({ ...t, font_family: t.font_family || FONTS[0].value }))
  )
  const [newText, setNewText] = useState('')
  const [addingText, setAddingText] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [playing, setPlaying] = useState(false)

  const [dragging, setDragging] = useState<string | null>(null)
  const [dragType, setDragType] = useState<'text' | 'waveform' | null>(null)
  const canvasRef = useRef<HTMLDivElement>(null)
  const waveCanvasRef = useRef<HTMLCanvasElement>(null)
  const animRef = useRef<number>(0)
  const barsRef = useRef<number[]>([])  // 현재 바 높이 (보간용)
  const targetRef = useRef<number[]>([])  // 목표 바 높이
  const tickCountRef = useRef(0)

  const bgPath = project.images?.background || project.images?.thumbnail || ''
  const bgUrl = storageUrl(bgPath)

  // ── 파형 그리기 ──
  const drawWaveform = useCallback(() => {
    const canvas = waveCanvasRef.current
    if (!canvas || !waveform.enabled) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    canvas.width = CANVAS_W
    canvas.height = CANVAS_H
    ctx.clearRect(0, 0, CANVAS_W, CANVAS_H)

    const count = waveform.bar_count || 60
    const maxH = CANVAS_H * (waveform.bar_height || 0.25)
    const y = waveform.position_y * CANVAS_H
    ctx.globalAlpha = waveform.opacity
    ctx.fillStyle = waveform.color

    // 바 배열 초기화/리사이즈
    if (barsRef.current.length !== count) {
      barsRef.current = Array.from({ length: count }, () => Math.random())
      targetRef.current = Array.from({ length: count }, () => Math.random())
    }

    // 보간: 현재값 → 목표값 천천히 이동
    const lerp = 0.08
    for (let i = 0; i < count; i++) {
      barsRef.current[i] += (targetRef.current[i] - barsRef.current[i]) * lerp
    }

    // 일정 간격으로 새 목표 설정 (속도 제어)
    tickCountRef.current++
    if (tickCountRef.current % 6 === 0) {
      for (let i = 0; i < count; i++) {
        targetRef.current[i] = Math.random() * 0.8 + 0.1
      }
    }

    if (waveform.style === 'circle') {
      // 원형: 둥근 막대가 원 주위로 배치
      const cx = CANVAS_W / 2
      const cy = y
      const radius = CANVAS_H * (waveform.circle_radius || 0.12)
      const bw = Math.max(2, (2 * Math.PI * radius) / count * (waveform.bar_width || 0.6))

      for (let i = 0; i < count; i++) {
        const h = barsRef.current[i] * maxH
        const angle = (i / count) * Math.PI * 2 - Math.PI / 2
        const innerX = cx + Math.cos(angle) * radius
        const innerY = cy + Math.sin(angle) * radius
        const outerX = cx + Math.cos(angle) * (radius + h)
        const outerY = cy + Math.sin(angle) * (radius + h)

        ctx.beginPath()
        ctx.moveTo(innerX, innerY)
        ctx.lineTo(outerX, outerY)
        ctx.lineWidth = bw
        ctx.lineCap = 'round'
        ctx.strokeStyle = waveform.color
        ctx.stroke()
      }
    } else {
      // bar / line
      const gap = CANVAS_W / count
      const bw = gap * (waveform.bar_width || 0.6)

      for (let i = 0; i < count; i++) {
        const h = barsRef.current[i] * maxH
        const x = gap * i + (gap - bw) / 2

        if (waveform.bar_align === 'center') {
          ctx.fillRect(x, y - h / 2, bw, h)
        } else if (waveform.bar_align === 'top') {
          ctx.fillRect(x, y, bw, h)
        } else {
          // bottom (기본)
          ctx.fillRect(x, y - h, bw, h)
        }
      }
    }
    ctx.globalAlpha = 1
  }, [waveform])

  useEffect(() => {
    if (!playing) {
      drawWaveform()
      return
    }
    let running = true
    const tick = () => {
      if (!running) return
      drawWaveform()
      animRef.current = requestAnimationFrame(tick)
    }
    tick()
    return () => { running = false; cancelAnimationFrame(animRef.current) }
  }, [playing, drawWaveform])

  useEffect(() => { drawWaveform() }, [drawWaveform])

  // ── 드래그 ──
  const handleMouseDown = (id: string, type: 'text' | 'waveform') => (e: React.MouseEvent) => {
    e.preventDefault()
    setDragging(id)
    setDragType(type)
  }

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging || !canvasRef.current) return
    const rect = canvasRef.current.getBoundingClientRect()
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height))
    if (dragType === 'waveform') {
      setWaveform(w => ({ ...w, position_y: y }))
    } else {
      setTextLayers(prev => prev.map(t => t.id === dragging ? { ...t, position_x: x, position_y: y } : t))
    }
  }, [dragging, dragType])

  const handleMouseUp = () => { setDragging(null); setDragType(null) }

  // ── 저장 ──
  const handleSave = async () => {
    setSaving(true)
    try {
      await api.layers.update(project.id, { ...layers, waveform_layer: waveform, text_layers: textLayers })
      await onRefresh()
    } finally { setSaving(false) }
  }

  const handleAddText = async () => {
    if (!newText.trim()) return
    setAddingText(true)
    try {
      await api.layers.addText(project.id, {
        text: newText.trim(), font_size: 36, font_family: FONTS[0].value,
        color: '#FFFFFF', position_x: 0.5, position_y: 0.1, bold: true,
      })
      setNewText('')
      await onRefresh()
      const updated = await api.layers.get(project.id)
      setTextLayers((updated.text_layers || []).map(t => ({ ...t, font_family: t.font_family || FONTS[0].value })))
    } finally { setAddingText(false) }
  }

  const handleDeleteText = async (layerId: string) => {
    await api.layers.deleteText(project.id, layerId)
    setTextLayers(prev => prev.filter(t => t.id !== layerId))
    await onRefresh()
  }

  const updateText = (id: string, u: Partial<TextLayerConfig>) => {
    setTextLayers(prev => prev.map(t => t.id === id ? { ...t, ...u } : t))
  }

  // 슬라이더 헬퍼
  const WfSlider = ({ label, value, min, max, step, unit, onChange }: {
    label: string; value: number; min: number; max: number; step: number; unit?: string
    onChange: (v: number) => void
  }) => (
    <div>
      <div className="flex justify-between text-[10px] text-gray-500 mb-0.5">
        <span>{label}</span><span>{typeof value === 'number' ? (unit === '%' ? Math.round(value * 100) + '%' : value) : value}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        className="w-full accent-purple-600 h-1" />
    </div>
  )

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold text-white">🎬 레이어 설정</h2>
        <div className="flex gap-2">
          <button onClick={() => setPlaying(p => !p)}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
              playing ? 'bg-red-700 hover:bg-red-600 text-white' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
            }`}>
            {playing ? '⏸ 정지' : '▶ 미리보기'}
          </button>
          <button onClick={handleSave} disabled={saving}
            className="bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white px-4 py-1.5 rounded-lg text-xs font-semibold">
            {saving ? '저장 중...' : '💾 저장'}
          </button>
        </div>
      </div>

      {/* ── 캔버스 ── */}
      <div ref={canvasRef}
        className="relative rounded-xl overflow-hidden border border-gray-800 mb-5 select-none mx-auto"
        style={{ width: CANVAS_W, height: CANVAS_H, background: '#000' }}
        onMouseMove={handleMouseMove} onMouseUp={handleMouseUp} onMouseLeave={handleMouseUp}>

        {bgUrl ? (
          <img src={bgUrl} alt="" className="absolute inset-0 w-full h-full object-cover" draggable={false} />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-gray-700 text-sm">배경 이미지 없음</div>
        )}

        {waveform.enabled && (
          <>
            <canvas ref={waveCanvasRef} width={CANVAS_W} height={CANVAS_H} className="absolute inset-0 pointer-events-none" />
            <div className="absolute left-0 right-0 h-6 cursor-ns-resize flex items-center justify-center group"
              style={{ top: `${waveform.position_y * 100}%`, transform: 'translateY(-50%)' }}
              onMouseDown={handleMouseDown('waveform', 'waveform')}>
              <div className="w-full h-px bg-white/20 group-hover:bg-white/40" />
              <span className="absolute text-[9px] text-white/40 bg-black/50 px-1.5 rounded group-hover:text-white/70">파형</span>
            </div>
          </>
        )}

        {textLayers.map(layer => (
          <div key={layer.id}
            className={`absolute cursor-move ${dragging === layer.id ? 'ring-2 ring-purple-400' : 'hover:ring-1 hover:ring-white/30'}`}
            style={{
              left: `${layer.position_x * 100}%`, top: `${layer.position_y * 100}%`,
              transform: 'translate(-50%, -50%)',
              fontSize: `${layer.font_size * (CANVAS_W / 1920)}px`,
              fontFamily: layer.font_family || FONTS[0].value,
              color: layer.color, fontWeight: layer.bold ? 'bold' : 'normal',
              textShadow: '2px 2px 4px rgba(0,0,0,0.8)', whiteSpace: 'nowrap', userSelect: 'none',
            }}
            onMouseDown={handleMouseDown(layer.id, 'text')}
            onDoubleClick={() => setEditingId(editingId === layer.id ? null : layer.id)}>
            {layer.text}
          </div>
        ))}
      </div>

      {/* ── 컨트롤 ── */}
      <div className="grid grid-cols-2 gap-4">
        {/* 파형 */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">파형</h3>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={waveform.enabled}
                onChange={e => setWaveform(w => ({ ...w, enabled: e.target.checked }))}
                className="w-3.5 h-3.5 accent-purple-600" />
              <span className="text-xs text-gray-500">켜기</span>
            </label>
          </div>
          {waveform.enabled && (
            <div className="space-y-2.5">
              {/* 스타일 */}
              <div className="flex gap-1.5">
                {(['bar', 'line', 'circle'] as const).map(s => (
                  <button key={s} onClick={() => setWaveform(w => ({ ...w, style: s }))}
                    className={`flex-1 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                      waveform.style === s ? 'bg-purple-600 text-white' : 'bg-gray-800 text-gray-500 hover:text-gray-300'
                    }`}>
                    {s === 'bar' ? '막대' : s === 'line' ? '라인' : '원형'}
                  </button>
                ))}
              </div>

              {/* 정렬 (bar/line만) */}
              {waveform.style !== 'circle' && (
                <div className="flex gap-1.5">
                  {(['bottom', 'center', 'top'] as const).map(a => (
                    <button key={a} onClick={() => setWaveform(w => ({ ...w, bar_align: a }))}
                      className={`flex-1 py-1 rounded-lg text-[10px] font-medium transition-colors ${
                        waveform.bar_align === a ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-500 hover:text-gray-300'
                      }`}>
                      {a === 'bottom' ? '⬇ 바닥' : a === 'center' ? '⬌ 중간' : '⬆ 위'}
                    </button>
                  ))}
                </div>
              )}

              {/* 색상 */}
              <div className="flex items-center gap-2">
                <input type="color" value={waveform.color}
                  onChange={e => setWaveform(w => ({ ...w, color: e.target.value }))}
                  className="w-7 h-7 rounded bg-gray-800 border border-gray-700 cursor-pointer" />
                <input value={waveform.color}
                  onChange={e => setWaveform(w => ({ ...w, color: e.target.value }))}
                  className="flex-1 bg-gray-800 text-white rounded-lg px-2 py-1 text-xs border border-gray-700 font-mono" />
              </div>

              {/* 슬라이더들 */}
              <WfSlider label="막대 개수" value={waveform.bar_count} min={10} max={200} step={5}
                onChange={v => { setWaveform(w => ({ ...w, bar_count: v })); barsRef.current = []; targetRef.current = [] }} />
              <WfSlider label="막대 너비" value={waveform.bar_width} min={0.1} max={1} step={0.05} unit="%"
                onChange={v => setWaveform(w => ({ ...w, bar_width: v }))} />
              <WfSlider label="막대 높이" value={waveform.bar_height} min={0.05} max={0.5} step={0.02} unit="%"
                onChange={v => setWaveform(w => ({ ...w, bar_height: v }))} />
              <WfSlider label="불투명도" value={waveform.opacity} min={0} max={1} step={0.05} unit="%"
                onChange={v => setWaveform(w => ({ ...w, opacity: v }))} />
              {waveform.style === 'circle' && (
                <WfSlider label="원 반지름" value={waveform.circle_radius} min={0.05} max={0.3} step={0.01} unit="%"
                  onChange={v => setWaveform(w => ({ ...w, circle_radius: v }))} />
              )}
            </div>
          )}
        </div>

        {/* 텍스트 */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">텍스트</h3>
          <div className="flex gap-1.5 mb-3">
            <input value={newText} onChange={e => setNewText(e.target.value)}
              placeholder="텍스트 입력..."
              className="flex-1 bg-gray-800 text-white rounded-lg px-2.5 py-1.5 text-xs border border-gray-700 focus:outline-none focus:border-purple-500"
              onKeyDown={e => { if (e.key === 'Enter') handleAddText() }} />
            <button onClick={handleAddText} disabled={addingText || !newText.trim()}
              className="bg-purple-600 hover:bg-purple-500 disabled:opacity-40 text-white px-3 py-1.5 rounded-lg text-xs font-semibold">+</button>
          </div>

          <div className="space-y-2 max-h-52 overflow-y-auto">
            {textLayers.length === 0 && (
              <div className="text-center py-4 text-gray-700 text-xs">드래그로 이동 · 더블클릭으로 편집</div>
            )}
            {textLayers.map(layer => (
              <div key={layer.id} className="bg-gray-800 rounded-lg p-2.5 space-y-2">
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded shrink-0 border border-gray-600" style={{ backgroundColor: layer.color }} />
                  <span className="flex-1 text-xs text-white truncate" style={{ fontFamily: layer.font_family }}>{layer.text}</span>
                  <button onClick={() => setEditingId(editingId === layer.id ? null : layer.id)}
                    className="text-gray-500 hover:text-gray-300 text-[10px]">{editingId === layer.id ? '▲' : '✏️'}</button>
                  <button onClick={() => handleDeleteText(layer.id)} className="text-gray-600 hover:text-red-400 text-[10px]">✕</button>
                </div>
                {editingId === layer.id && (
                  <div className="space-y-2 pt-1.5 border-t border-gray-700">
                    <input value={layer.text} onChange={e => updateText(layer.id, { text: e.target.value })}
                      className="w-full bg-gray-900 text-white rounded px-2 py-1 text-xs border border-gray-700" />
                    {/* 폰트 */}
                    <select value={layer.font_family || FONTS[0].value}
                      onChange={e => updateText(layer.id, { font_family: e.target.value })}
                      className="w-full bg-gray-900 text-white rounded px-2 py-1 text-xs border border-gray-700">
                      {FONTS.map(f => (
                        <option key={f.value} value={f.value} style={{ fontFamily: f.value }}>{f.label}</option>
                      ))}
                    </select>
                    <div className="flex gap-2 items-center">
                      <input type="color" value={layer.color}
                        onChange={e => updateText(layer.id, { color: e.target.value })}
                        className="w-6 h-6 rounded cursor-pointer bg-gray-900 border border-gray-700" />
                      <input type="number" value={layer.font_size}
                        onChange={e => updateText(layer.id, { font_size: parseInt(e.target.value) || 24 })}
                        className="w-14 bg-gray-900 text-white rounded px-2 py-1 text-xs border border-gray-700" min={12} max={200} />
                      <span className="text-[10px] text-gray-600">px</span>
                      <button onClick={() => updateText(layer.id, { bold: !layer.bold })}
                        className={`px-2 py-0.5 rounded text-xs font-bold transition-colors ${
                          layer.bold ? 'bg-purple-600 text-white' : 'bg-gray-900 text-gray-500 border border-gray-700'
                        }`}>B</button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
      <p className="text-[10px] text-gray-700 mt-3 text-center">드래그로 위치 이동 · 더블클릭 텍스트 편집 · 파형 라인 드래그</p>
    </div>
  )
}
