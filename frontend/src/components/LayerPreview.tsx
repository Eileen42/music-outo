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

const DEFAULT_WAVEFORM: WaveformLayerConfig = {
  enabled: true,
  style: 'bar',
  color: '#FFFFFF',
  opacity: 0.8,
  position_y: 0.7,
}

const CANVAS_W = 768
const CANVAS_H = 432 // 16:9

export default function LayerPreview({ project, onRefresh }: Props) {
  const [saving, setSaving] = useState(false)
  const layers = project.layers || { background_video: null, waveform_layer: null, text_layers: [] }
  const wf = layers.waveform_layer || DEFAULT_WAVEFORM

  const [waveform, setWaveform] = useState<WaveformLayerConfig>(wf)
  const [textLayers, setTextLayers] = useState<TextLayerConfig[]>(layers.text_layers || [])
  const [newText, setNewText] = useState('')
  const [addingText, setAddingText] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [playing, setPlaying] = useState(false)

  // 드래그 상태
  const [dragging, setDragging] = useState<string | null>(null)
  const [dragType, setDragType] = useState<'text' | 'waveform' | null>(null)
  const canvasRef = useRef<HTMLDivElement>(null)
  const waveCanvasRef = useRef<HTMLCanvasElement>(null)
  const animRef = useRef<number>(0)

  // 배경 이미지
  const bgPath = project.images?.background || project.images?.thumbnail || ''
  const bgUrl = storageUrl(bgPath)

  // ── 파형 애니메이션 ──
  const drawWaveform = useCallback(() => {
    const canvas = waveCanvasRef.current
    if (!canvas || !waveform.enabled) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    canvas.width = CANVAS_W
    canvas.height = CANVAS_H
    ctx.clearRect(0, 0, CANVAS_W, CANVAS_H)

    const y = waveform.position_y * CANVAS_H
    const barCount = waveform.style === 'line' ? 200 : 80
    const barWidth = waveform.style === 'line' ? 2 : CANVAS_W / barCount - 2
    const maxH = CANVAS_H * 0.25

    ctx.globalAlpha = waveform.opacity

    for (let i = 0; i < barCount; i++) {
      const h = (Math.random() * 0.6 + 0.2) * maxH
      const x = (CANVAS_W / barCount) * i

      if (waveform.style === 'circle') {
        // 원형: 중앙 원 주위
        const cx = CANVAS_W / 2
        const cy = y
        const radius = 80
        const angle = (i / barCount) * Math.PI * 2
        const bx = cx + Math.cos(angle) * (radius + h * 0.5)
        const by = cy + Math.sin(angle) * (radius + h * 0.5)
        ctx.beginPath()
        ctx.arc(bx, by, 2, 0, Math.PI * 2)
        ctx.fillStyle = waveform.color
        ctx.fill()
      } else {
        ctx.fillStyle = waveform.color
        if (waveform.style === 'line') {
          ctx.fillRect(x, y - h / 2, barWidth, h)
        } else {
          ctx.fillRect(x + 1, y - h, barWidth, h)
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

  // 초기 정적 그리기
  useEffect(() => { drawWaveform() }, [drawWaveform])

  // ── 드래그 핸들러 ──
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
      setTextLayers(prev => prev.map(t =>
        t.id === dragging ? { ...t, position_x: x, position_y: y } : t
      ))
    }
  }, [dragging, dragType])

  const handleMouseUp = () => {
    setDragging(null)
    setDragType(null)
  }

  // ── 저장 ──
  const handleSave = async () => {
    setSaving(true)
    try {
      await api.layers.update(project.id, {
        ...layers,
        waveform_layer: waveform,
        text_layers: textLayers,
      })
      await onRefresh()
    } finally { setSaving(false) }
  }

  const handleAddText = async () => {
    if (!newText.trim()) return
    setAddingText(true)
    try {
      await api.layers.addText(project.id, {
        text: newText.trim(),
        font_size: 36,
        color: '#FFFFFF',
        position_x: 0.5,
        position_y: 0.1,
        bold: true,
      })
      setNewText('')
      await onRefresh()
      // 로컬 동기화
      const updated = await api.layers.get(project.id)
      setTextLayers(updated.text_layers || [])
    } finally { setAddingText(false) }
  }

  const handleDeleteText = async (layerId: string) => {
    await api.layers.deleteText(project.id, layerId)
    setTextLayers(prev => prev.filter(t => t.id !== layerId))
    await onRefresh()
  }

  const updateTextLayer = (id: string, updates: Partial<TextLayerConfig>) => {
    setTextLayers(prev => prev.map(t => t.id === id ? { ...t, ...updates } : t))
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold text-white">🎬 레이어 설정</h2>
        <div className="flex gap-2">
          <button
            onClick={() => setPlaying(p => !p)}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
              playing ? 'bg-red-700 hover:bg-red-600 text-white' : 'bg-gray-700 hover:bg-gray-600 text-gray-300'
            }`}
          >
            {playing ? '⏸ 정지' : '▶ 파형 미리보기'}
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white px-4 py-1.5 rounded-lg text-xs font-semibold"
          >
            {saving ? '저장 중...' : '💾 저장'}
          </button>
        </div>
      </div>

      {/* ── 미리보기 캔버스 ── */}
      <div
        ref={canvasRef}
        className="relative rounded-xl overflow-hidden border border-gray-800 mb-5 select-none"
        style={{ width: CANVAS_W, height: CANVAS_H, background: '#000' }}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        {/* 배경 이미지 */}
        {bgUrl && (
          <img
            src={bgUrl}
            alt="배경"
            className="absolute inset-0 w-full h-full object-cover"
            draggable={false}
          />
        )}
        {!bgUrl && (
          <div className="absolute inset-0 flex items-center justify-center text-gray-700 text-sm">
            배경 이미지를 먼저 업로드하세요 (이미지 설정 단계)
          </div>
        )}

        {/* 파형 캔버스 */}
        {waveform.enabled && (
          <>
            <canvas
              ref={waveCanvasRef}
              width={CANVAS_W}
              height={CANVAS_H}
              className="absolute inset-0 pointer-events-none"
            />
            {/* 파형 드래그 핸들 (Y 위치 라인) */}
            <div
              className="absolute left-0 right-0 h-6 cursor-ns-resize flex items-center justify-center group"
              style={{ top: `${waveform.position_y * 100}%`, transform: 'translateY(-50%)' }}
              onMouseDown={handleMouseDown('waveform', 'waveform')}
            >
              <div className="w-full h-px bg-white/20 group-hover:bg-white/40 transition-colors" />
              <span className="absolute text-[9px] text-white/40 bg-black/50 px-1 rounded group-hover:text-white/70">
                파형
              </span>
            </div>
          </>
        )}

        {/* 텍스트 레이어 */}
        {textLayers.map(layer => (
          <div
            key={layer.id}
            className={`absolute cursor-move transition-shadow ${
              dragging === layer.id ? 'ring-2 ring-purple-400' : 'hover:ring-1 hover:ring-white/30'
            }`}
            style={{
              left: `${layer.position_x * 100}%`,
              top: `${layer.position_y * 100}%`,
              transform: 'translate(-50%, -50%)',
              fontSize: `${layer.font_size * (CANVAS_W / 1920)}px`,
              color: layer.color,
              fontWeight: layer.bold ? 'bold' : 'normal',
              textShadow: '2px 2px 4px rgba(0,0,0,0.8)',
              whiteSpace: 'nowrap',
              userSelect: 'none',
            }}
            onMouseDown={handleMouseDown(layer.id, 'text')}
            onDoubleClick={() => setEditingId(editingId === layer.id ? null : layer.id)}
          >
            {layer.text}
          </div>
        ))}
      </div>

      {/* ── 컨트롤 패널 ── */}
      <div className="grid grid-cols-2 gap-4">
        {/* 파형 설정 */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">파형</h3>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={waveform.enabled}
                onChange={e => setWaveform(w => ({ ...w, enabled: e.target.checked }))}
                className="w-3.5 h-3.5 accent-purple-600"
              />
              <span className="text-xs text-gray-500">켜기</span>
            </label>
          </div>
          {waveform.enabled && (
            <div className="space-y-3">
              <div className="flex gap-2">
                {(['bar', 'line', 'circle'] as const).map(s => (
                  <button
                    key={s}
                    onClick={() => setWaveform(w => ({ ...w, style: s }))}
                    className={`flex-1 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                      waveform.style === s ? 'bg-purple-600 text-white' : 'bg-gray-800 text-gray-500 hover:text-gray-300'
                    }`}
                  >
                    {s === 'bar' ? '막대' : s === 'line' ? '라인' : '원형'}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500 w-12">색상</span>
                <input
                  type="color"
                  value={waveform.color}
                  onChange={e => setWaveform(w => ({ ...w, color: e.target.value }))}
                  className="w-7 h-7 rounded bg-gray-800 border border-gray-700 cursor-pointer"
                />
                <input
                  value={waveform.color}
                  onChange={e => setWaveform(w => ({ ...w, color: e.target.value }))}
                  className="flex-1 bg-gray-800 text-white rounded-lg px-2 py-1 text-xs border border-gray-700 font-mono"
                />
              </div>
              <div>
                <div className="flex justify-between text-xs text-gray-500 mb-1">
                  <span>불투명도</span><span>{Math.round(waveform.opacity * 100)}%</span>
                </div>
                <input
                  type="range" min={0} max={1} step={0.05}
                  value={waveform.opacity}
                  onChange={e => setWaveform(w => ({ ...w, opacity: parseFloat(e.target.value) }))}
                  className="w-full accent-purple-600 h-1"
                />
              </div>
            </div>
          )}
        </div>

        {/* 텍스트 설정 */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">텍스트</h3>

          {/* 추가 */}
          <div className="flex gap-1.5 mb-3">
            <input
              value={newText}
              onChange={e => setNewText(e.target.value)}
              placeholder="텍스트 입력..."
              className="flex-1 bg-gray-800 text-white rounded-lg px-2.5 py-1.5 text-xs border border-gray-700 focus:outline-none focus:border-purple-500"
              onKeyDown={e => { if (e.key === 'Enter') handleAddText() }}
            />
            <button
              onClick={handleAddText}
              disabled={addingText || !newText.trim()}
              className="bg-purple-600 hover:bg-purple-500 disabled:opacity-40 text-white px-3 py-1.5 rounded-lg text-xs font-semibold"
            >
              +
            </button>
          </div>

          {/* 레이어 목록 + 인라인 편집 */}
          <div className="space-y-2 max-h-48 overflow-y-auto">
            {textLayers.length === 0 && (
              <div className="text-center py-4 text-gray-700 text-xs">더블클릭으로 편집, 드래그로 이동</div>
            )}
            {textLayers.map(layer => (
              <div key={layer.id} className="bg-gray-800 rounded-lg p-2.5 space-y-2">
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded shrink-0 border border-gray-600" style={{ backgroundColor: layer.color }} />
                  <span className="flex-1 text-xs text-white truncate">{layer.text}</span>
                  <button
                    onClick={() => setEditingId(editingId === layer.id ? null : layer.id)}
                    className="text-gray-500 hover:text-gray-300 text-[10px]"
                  >
                    {editingId === layer.id ? '▲' : '✏️'}
                  </button>
                  <button onClick={() => handleDeleteText(layer.id)} className="text-gray-600 hover:text-red-400 text-[10px]">✕</button>
                </div>

                {editingId === layer.id && (
                  <div className="space-y-2 pt-1 border-t border-gray-700">
                    <input
                      value={layer.text}
                      onChange={e => updateTextLayer(layer.id, { text: e.target.value })}
                      className="w-full bg-gray-900 text-white rounded px-2 py-1 text-xs border border-gray-700"
                    />
                    <div className="flex gap-2 items-center">
                      <input
                        type="color"
                        value={layer.color}
                        onChange={e => updateTextLayer(layer.id, { color: e.target.value })}
                        className="w-6 h-6 rounded cursor-pointer bg-gray-900 border border-gray-700"
                      />
                      <input
                        type="number"
                        value={layer.font_size}
                        onChange={e => updateTextLayer(layer.id, { font_size: parseInt(e.target.value) || 24 })}
                        className="w-16 bg-gray-900 text-white rounded px-2 py-1 text-xs border border-gray-700"
                        min={12} max={120}
                      />
                      <span className="text-[10px] text-gray-600">px</span>
                      <button
                        onClick={() => updateTextLayer(layer.id, { bold: !layer.bold })}
                        className={`px-2 py-0.5 rounded text-xs font-bold transition-colors ${
                          layer.bold ? 'bg-purple-600 text-white' : 'bg-gray-900 text-gray-500 border border-gray-700'
                        }`}
                      >
                        B
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      <p className="text-[10px] text-gray-700 mt-3 text-center">
        캔버스에서 드래그로 위치 이동 · 더블클릭으로 텍스트 편집 · 파형 라인을 위아래로 드래그
      </p>
    </div>
  )
}
