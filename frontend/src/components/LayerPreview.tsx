import { useState, useRef, useEffect, useCallback } from 'react'
import type { Project, WaveformLayerConfig, TextLayerConfig, TextShadow, TextAnimation, EffectLayerConfig, LayerTemplate } from '../types'
import { api } from '../api/client'

interface Props { project: Project; onRefresh: () => void }

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'
function storageUrl(p: string): string {
  if (!p) return ''; const r = p.replace(/\\/g, '/').split('storage/')[1]; return r ? `${API_BASE}/storage/${r}` : ''
}

const FONTS = [
  { value: 'SeoulHangangB', label: '서울한강체B' },
  { value: '"Palatino Linotype"', label: 'Palatino Bold Italic' },
  { value: 'Pretendard, sans-serif', label: 'Pretendard' },
  { value: '"Noto Sans KR", sans-serif', label: 'Noto Sans KR' },
  { value: '"Noto Serif KR", serif', label: 'Noto Serif (명조)' },
  { value: 'Arial, sans-serif', label: 'Arial' },
  { value: 'Georgia, serif', label: 'Georgia' },
  { value: 'Impact, sans-serif', label: 'Impact' },
  { value: '"Malgun Gothic", sans-serif', label: '맑은 고딕' },
]
const ANIM_TYPES = [
  { value: 'none', label: '없음' },
  { value: 'fade_in', label: '페이드 인' },
  { value: 'fade_out', label: '페이드 아웃' },
  { value: 'slide_up', label: '슬라이드 업' },
  { value: 'slide_down', label: '슬라이드 다운' },
]

const DEF_SHADOW: TextShadow = { enabled: false, color: '#000000', alpha: 0.36, angle: -45, distance: 5, blur: 1.75 }
const DEF_ANIM: TextAnimation = { type: 'none', duration: 0 }
const DEF_WF: WaveformLayerConfig = {
  enabled: true, style: 'bar', color: '#FFFFFF', opacity: 0.8,
  position_x: 0.5, position_y: 0.7, bar_count: 60, bar_width: 4, bar_gap: 2,
  bar_height: 120, bar_min: 0.1, bar_align: 'bottom', scale: 1.0, circle_radius: 0.12,
}
const CW = 640, CH = 360, S = CW / 1920

function mgWf(s: Partial<WaveformLayerConfig> | null): WaveformLayerConfig { return { ...DEF_WF, ...(s || {}) } }
function mgTxt(t: Partial<TextLayerConfig> & { id: string; text: string }): TextLayerConfig {
  const base: TextLayerConfig = {
    id: t.id, text: t.text || '', font_size: 36, font_family: FONTS[0].value, color: '#FFFFFF', alpha: 1,
    position_x: 0.5, position_y: 0.1, scale_x: 1, scale_y: 1,
    bold: false, italic: false, letter_spacing: 0, line_spacing: 0,
    alignment: 'center', shadow: { ...DEF_SHADOW }, animation_in: { ...DEF_ANIM }, animation_out: { ...DEF_ANIM }, role: 'custom',
  }
  return {
    ...base, ...t,
    font_family: t.font_family || base.font_family,
    shadow: { ...DEF_SHADOW, ...(t.shadow || {}) },
    animation_in: { ...DEF_ANIM, ...(t.animation_in || {}) },
    animation_out: { ...DEF_ANIM, ...(t.animation_out || {}) },
  }
}
function bellEnvelope(i: number, n: number): number { const x = (i / (n - 1)) * 2 - 1; return 0.2 + 0.8 * Math.exp(-3 * x * x) }

interface Particle { x: number; y: number; vx: number; vy: number; size: number; phase: number }
function initP(n: number): Particle[] {
  return Array.from({ length: n }, () => ({
    x: Math.random(), y: Math.random(), vx: (Math.random() - 0.5) * 0.0008, vy: (Math.random() - 0.5) * 0.0006,
    size: Math.random() * 3 + 1, phase: Math.random() * Math.PI * 2,
  }))
}

// ── 슬라이더 헬퍼 ──
function Sl({ label, value, min, max, step, fmt, onChange }: {
  label: string; value: number; min: number; max: number; step: number; fmt?: (v: number) => string; onChange: (v: number) => void
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[9px] text-gray-500 w-10 shrink-0">{label}</span>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(parseFloat(e.target.value))} className="flex-1 accent-purple-600 h-1" />
      <span className="text-[9px] text-gray-500 w-10 text-right shrink-0">{fmt ? fmt(value) : value}</span>
    </div>
  )
}

// ── 접기/펴기 섹션 ──
function Section({ title, open, onToggle, badge, children }: {
  title: string; open: boolean; onToggle: () => void; badge?: string; children: React.ReactNode
}) {
  return (
    <div className="border-b border-gray-800">
      <button onClick={onToggle} className="w-full flex items-center gap-2 px-3 py-2 hover:bg-gray-800/50 text-left">
        <span className="text-[10px] text-gray-600">{open ? '▼' : '▶'}</span>
        <span className="text-xs font-semibold text-gray-300 flex-1">{title}</span>
        {badge && <span className="text-[9px] bg-gray-800 text-gray-500 px-1.5 py-0.5 rounded-full">{badge}</span>}
      </button>
      {open && <div className="px-3 pb-3 space-y-2">{children}</div>}
    </div>
  )
}

export default function LayerPreview({ project, onRefresh }: Props) {
  const [saving, setSaving] = useState(false)
  const layers = project.layers || { background_video: null, waveform_layer: null, text_layers: [], effect_layers: [] }
  const [wf, setWf] = useState<WaveformLayerConfig>(mgWf(layers.waveform_layer))
  const [texts, setTexts] = useState<TextLayerConfig[]>((layers.text_layers || []).map(t => mgTxt(t as TextLayerConfig)))
  const [effects, setEffects] = useState<EffectLayerConfig[]>(layers.effect_layers || [])
  const [playing, setPlaying] = useState(false)
  const [templates, setTemplates] = useState<LayerTemplate[]>([])
  const [tplName, setTplName] = useState('')
  const [newText, setNewText] = useState('')
  const [editId, setEditId] = useState<string | null>(texts[0]?.id || null)

  // 자막
  const subtitleEntries = project.subtitle_entries || []
  const [subStyle, setSubStyle] = useState<Partial<TextLayerConfig>>(
    (layers as unknown as { subtitle_style?: Partial<TextLayerConfig> }).subtitle_style || {}
  )
  const [subPreviewIdx, setSubPreviewIdx] = useState(0)
  const [playTime, setPlayTime] = useState(0) // 재생 시뮬레이션 시간(초)

  // 섹션 토글
  const [openSec, setOpenSec] = useState<Record<string, boolean>>({ waveform: true, text: true, subtitle: true, effect: true, template: false })
  const toggle = (k: string) => setOpenSec(p => ({ ...p, [k]: !p[k] }))

  // 드래그
  type DragMode = 'move-wf' | 'move-text' | 'resize-wf' | 'resize-text'
  const [dragMode, setDragMode] = useState<DragMode | null>(null)
  const [dragId, setDragId] = useState<string | null>(null)
  const dragStartRef = useRef<{ mx: number; my: number; origSize: number } | null>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const cvRef = useRef<HTMLCanvasElement>(null)
  const fxRef = useRef<HTMLCanvasElement>(null)
  const animRef = useRef(0)
  const barsRef = useRef<number[]>([])
  const targRef = useRef<number[]>([])
  const tickRef = useRef(0)
  const particlesRef = useRef<Particle[]>(initP(40))
  const bgUrl = storageUrl(project.images?.background || project.images?.thumbnail || '')

  useEffect(() => { if (project.channel_id) api.channels.listTemplates(project.channel_id).then(setTemplates).catch(() => {}) }, [project.channel_id])

  // ── 파형 그리기 ──
  const drawWf = useCallback(() => {
    const cv = cvRef.current; if (!cv) return
    const ctx = cv.getContext('2d')!; cv.width = CW; cv.height = CH; ctx.clearRect(0, 0, CW, CH)
    if (!wf.enabled) return
    const count = wf.bar_count || 60, sc = wf.scale * S, bw = wf.bar_width * sc, gap = wf.bar_gap * sc, maxH = wf.bar_height * sc
    const cx = wf.position_x * CW, cy = wf.position_y * CH, totalW = count * (bw + gap), startX = cx - totalW / 2
    ctx.globalAlpha = wf.opacity; ctx.fillStyle = wf.color
    if (barsRef.current.length !== count) { barsRef.current = Array.from({ length: count }, () => Math.random()); targRef.current = Array.from({ length: count }, () => Math.random()) }
    for (let i = 0; i < count; i++) barsRef.current[i] += (targRef.current[i] - barsRef.current[i]) * 0.08
    const bmin = wf.bar_min ?? 0.1; tickRef.current++
    if (tickRef.current % 6 === 0) for (let i = 0; i < count; i++) targRef.current[i] = Math.random() * (1 - bmin) + bmin
    if (wf.style === 'circle') {
      const r = CH * (wf.circle_radius || 0.12) * wf.scale, cbw = Math.max(2, bw * 0.8)
      for (let i = 0; i < count; i++) { const env = bellEnvelope(i, count), h = barsRef.current[i] * maxH * env, a = (i / count) * Math.PI * 2 - Math.PI / 2; ctx.beginPath(); ctx.moveTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r); ctx.lineTo(cx + Math.cos(a) * (r + h), cy + Math.sin(a) * (r + h)); ctx.lineWidth = cbw; ctx.lineCap = 'round'; ctx.strokeStyle = wf.color; ctx.stroke() }
    } else {
      for (let i = 0; i < count; i++) { const env = bellEnvelope(i, count), h = barsRef.current[i] * maxH * env, x = startX + i * (bw + gap); if (wf.bar_align === 'center') ctx.fillRect(x, cy - h / 2, bw, h); else if (wf.bar_align === 'top') ctx.fillRect(x, cy, bw, h); else ctx.fillRect(x, cy - h, bw, h) }
    }
    ctx.globalAlpha = 1
  }, [wf])
  const drawFx = useCallback(() => {
    const cv = fxRef.current; if (!cv) return; const ctx = cv.getContext('2d')!; cv.width = CW; cv.height = CH; ctx.clearRect(0, 0, CW, CH)
    if (!effects.some(e => e.enabled)) return
    const speed = effects.find(e => e.enabled)?.params?.speed ?? 0.14
    for (const p of particlesRef.current) { p.x += p.vx * (1 + speed * 5); p.y += p.vy * (1 + speed * 5); p.phase += 0.02; if (p.x < 0 || p.x > 1) p.vx *= -1; if (p.y < 0 || p.y > 1) p.vy *= -1; const fl = 0.3 + 0.7 * (0.5 + 0.5 * Math.sin(p.phase)); ctx.beginPath(); ctx.arc(p.x * CW, p.y * CH, p.size, 0, Math.PI * 2); ctx.fillStyle = `rgba(255,255,180,${fl * 0.6})`; ctx.fill(); ctx.beginPath(); ctx.arc(p.x * CW, p.y * CH, p.size * 3, 0, Math.PI * 2); ctx.fillStyle = `rgba(255,255,150,${fl * 0.15})`; ctx.fill() }
  }, [effects])
  useEffect(() => { if (!playing) { drawWf(); drawFx(); return }; let on = true; const t = () => { if (!on) return; drawWf(); drawFx(); animRef.current = requestAnimationFrame(t) }; t(); return () => { on = false; cancelAnimationFrame(animRef.current) } }, [playing, drawWf, drawFx])
  useEffect(() => { drawWf(); drawFx() }, [drawWf, drawFx])

  // 재생 시 자막 타임코드 시뮬레이션
  useEffect(() => {
    if (!playing || subtitleEntries.length === 0) return
    const start = Date.now() - playTime * 1000
    const timer = setInterval(() => {
      const elapsed = (Date.now() - start) / 1000
      setPlayTime(elapsed)
      // 현재 시간에 해당하는 자막 찾기
      const idx = subtitleEntries.findIndex(e => e.start <= elapsed && e.end >= elapsed)
      if (idx >= 0) setSubPreviewIdx(idx)
    }, 200)
    return () => clearInterval(timer)
  }, [playing, subtitleEntries.length])

  // ── 드래그 ──
  const startDrag = (mode: DragMode, id: string) => (e: React.MouseEvent) => { e.preventDefault(); e.stopPropagation(); setDragMode(mode); setDragId(id); const l = texts.find(t => t.id === id); dragStartRef.current = { mx: e.clientY, my: e.clientY, origSize: l?.font_size || 36 } }
  const onMove = useCallback((e: React.MouseEvent) => { if (!dragMode || !boxRef.current) return; const r = boxRef.current.getBoundingClientRect(); const x = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)); const y = Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)); if (dragMode === 'move-wf') setWf(w => ({ ...w, position_x: x, position_y: y })); else if (dragMode === 'move-text') setTexts(p => p.map(t => t.id === dragId ? { ...t, position_x: x, position_y: y } : t)); else if (dragMode === 'resize-wf') { const origW = (wf.bar_count * (wf.bar_width + wf.bar_gap) * S) / CW; const dx = Math.abs(x - wf.position_x) * 2; if (origW > 0) setWf(w => ({ ...w, scale: Math.max(0.2, Math.min(5, dx / origW)) })) } else if (dragMode === 'resize-text' && dragStartRef.current) { const dy = e.clientY - dragStartRef.current.mx; setTexts(p => p.map(t => t.id === dragId ? { ...t, font_size: Math.max(12, Math.min(200, Math.round(dragStartRef.current!.origSize - dy * 0.5))) } : t)) } }, [dragMode, dragId, wf])
  const onUp = () => { setDragMode(null); setDragId(null); dragStartRef.current = null }

  // ── CRUD ──
  const save = async () => { setSaving(true); try { await api.layers.update(project.id, { ...layers, waveform_layer: wf, text_layers: texts, effect_layers: effects, subtitle_style: subStyle }); await onRefresh() } finally { setSaving(false) } }
  const addTxt = async () => { if (!newText.trim()) return; const t = mgTxt({ id: crypto.randomUUID(), text: newText.trim() }); setTexts(p => [...p, t]); setEditId(t.id); setNewText('') }
  const delTxt = (id: string) => { setTexts(p => p.filter(t => t.id !== id)); if (editId === id) setEditId(null) }
  const updTxt = (id: string, u: Partial<TextLayerConfig>) => setTexts(p => p.map(t => t.id === id ? { ...t, ...u } : t))

  // 자막 미리보기 텍스트
  const subPreview = subtitleEntries[subPreviewIdx]

  // 파형 바운딩
  const wfNW = wf.bar_count * ((wf.bar_width + wf.bar_gap) * S) * wf.scale
  const wfNH = wf.bar_height * S * wf.scale

  return (
    <div className="flex gap-4">
      {/* ═══ 왼쪽 컨트롤 패널 ═══ */}
      <div className="w-64 shrink-0 bg-gray-900 border border-gray-800 rounded-xl overflow-hidden max-h-[80vh] overflow-y-auto">
        {/* 파형 */}
        <Section title="🎵 파형" open={openSec.waveform} onToggle={() => toggle('waveform')} badge={wf.enabled ? 'ON' : 'OFF'}>
          <label className="flex items-center gap-2 cursor-pointer mb-1">
            <input type="checkbox" checked={wf.enabled} onChange={e => setWf(w => ({ ...w, enabled: e.target.checked }))} className="w-3 h-3 accent-purple-600" />
            <span className="text-[10px] text-gray-400">활성화</span>
          </label>
          {wf.enabled && <>
            <div className="flex gap-1">{(['bar', 'line', 'circle'] as const).map(s => (<button key={s} onClick={() => setWf(w => ({ ...w, style: s }))} className={`flex-1 py-1 rounded text-[10px] ${wf.style === s ? 'bg-purple-600 text-white' : 'bg-gray-800 text-gray-500'}`}>{s === 'bar' ? '막대' : s === 'line' ? '라인' : '원형'}</button>))}</div>
            {wf.style !== 'circle' && <div className="flex gap-1">{(['bottom', 'center', 'top'] as const).map(a => (<button key={a} onClick={() => setWf(w => ({ ...w, bar_align: a }))} className={`flex-1 py-0.5 rounded text-[9px] ${wf.bar_align === a ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-500'}`}>{a === 'bottom' ? '바닥' : a === 'center' ? '중간' : '위'}</button>))}</div>}
            <div className="flex items-center gap-1"><input type="color" value={wf.color} onChange={e => setWf(w => ({ ...w, color: e.target.value }))} className="w-5 h-5 rounded bg-gray-800 border border-gray-700 cursor-pointer" /><input value={wf.color} onChange={e => setWf(w => ({ ...w, color: e.target.value }))} className="flex-1 bg-gray-800 text-white rounded px-1.5 py-0.5 text-[10px] border border-gray-700 font-mono" /></div>
            <Sl label="크기" value={wf.scale} min={0.2} max={3} step={0.1} fmt={v => `${Math.round(v * 100)}%`} onChange={v => setWf(w => ({ ...w, scale: v }))} />
            <Sl label="개수" value={wf.bar_count} min={10} max={200} step={5} fmt={v => `${v}`} onChange={v => { setWf(w => ({ ...w, bar_count: v })); barsRef.current = []; targRef.current = [] }} />
            <Sl label="너비" value={wf.bar_width} min={1} max={20} step={1} fmt={v => `${v}px`} onChange={v => setWf(w => ({ ...w, bar_width: v }))} />
            <Sl label="간격" value={wf.bar_gap} min={0} max={15} step={1} fmt={v => `${v}px`} onChange={v => setWf(w => ({ ...w, bar_gap: v }))} />
            <Sl label="높이" value={wf.bar_height} min={20} max={400} step={10} fmt={v => `${v}px`} onChange={v => setWf(w => ({ ...w, bar_height: v }))} />
            <Sl label="편차" value={wf.bar_min ?? 0.1} min={0} max={0.95} step={0.05} fmt={v => v >= 0.9 ? '균일' : `${Math.round(v * 100)}%`} onChange={v => setWf(w => ({ ...w, bar_min: v }))} />
            <Sl label="투명도" value={wf.opacity} min={0} max={1} step={0.05} fmt={v => `${Math.round(v * 100)}%`} onChange={v => setWf(w => ({ ...w, opacity: v }))} />
          </>}
        </Section>

        {/* 텍스트 */}
        <Section title="📝 텍스트" open={openSec.text} onToggle={() => toggle('text')} badge={`${texts.length}`}>
          <div className="flex gap-1 mb-1"><input value={newText} onChange={e => setNewText(e.target.value)} placeholder="텍스트 추가..." className="flex-1 bg-gray-800 text-white rounded px-2 py-1 text-[10px] border border-gray-700" onKeyDown={e => { if (e.key === 'Enter') addTxt() }} /><button onClick={addTxt} disabled={!newText.trim()} className="bg-purple-600 hover:bg-purple-500 disabled:opacity-40 text-white px-2 py-1 rounded text-[10px]">+</button></div>
          {texts.map(l => (
            <div key={l.id} className={`rounded-lg overflow-hidden border ${editId === l.id ? 'border-purple-600 bg-gray-800' : 'border-gray-800 bg-gray-800/50'}`}>
              <div className="flex items-center gap-1.5 px-2 py-1.5 cursor-pointer" onClick={() => setEditId(editId === l.id ? null : l.id)}>
                <div className="w-2 h-2 rounded-sm shrink-0" style={{ backgroundColor: l.color }} />
                <span className="flex-1 text-[10px] text-white truncate">{l.text}</span>
                <span className="text-[8px] text-gray-600">{l.role}</span>
                <button onClick={e => { e.stopPropagation(); delTxt(l.id) }} className="text-gray-600 hover:text-red-400 text-[10px]">✕</button>
              </div>
              {editId === l.id && (
                <div className="px-2 pb-2 space-y-1.5 border-t border-gray-700 pt-1.5">
                  <input value={l.text} onChange={e => updTxt(l.id, { text: e.target.value })} className="w-full bg-gray-900 text-white rounded px-2 py-1 text-[10px] border border-gray-700" />
                  <div className="flex gap-1"><select value={l.font_family} onChange={e => updTxt(l.id, { font_family: e.target.value })} className="flex-1 bg-gray-900 text-white rounded px-1 py-0.5 text-[10px] border border-gray-700">{FONTS.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}</select><select value={l.role} onChange={e => updTxt(l.id, { role: e.target.value as TextLayerConfig['role'] })} className="w-14 bg-gray-900 text-white rounded px-1 py-0.5 text-[10px] border border-gray-700"><option value="title">제목</option><option value="subtitle">자막</option><option value="description">설명</option><option value="custom">커스텀</option></select></div>
                  <div className="flex gap-1 items-center flex-wrap"><input type="color" value={l.color} onChange={e => updTxt(l.id, { color: e.target.value })} className="w-5 h-5 rounded cursor-pointer" /><input type="number" value={l.font_size} onChange={e => updTxt(l.id, { font_size: parseInt(e.target.value) || 24 })} className="w-10 bg-gray-900 text-white rounded px-1 py-0.5 text-[10px] border border-gray-700" min={8} max={200} /><span className="text-[8px] text-gray-600">px</span><button onClick={() => updTxt(l.id, { bold: !l.bold })} className={`px-1 py-0.5 rounded text-[10px] font-bold ${l.bold ? 'bg-purple-600 text-white' : 'bg-gray-900 text-gray-500'}`}>B</button><button onClick={() => updTxt(l.id, { italic: !l.italic })} className={`px-1 py-0.5 rounded text-[10px] italic ${l.italic ? 'bg-purple-600 text-white' : 'bg-gray-900 text-gray-500'}`}>I</button></div>
                  <Sl label="투명" value={l.alpha ?? 1} min={0} max={1} step={0.05} fmt={v => `${Math.round(v * 100)}%`} onChange={v => updTxt(l.id, { alpha: v })} />
                  <div className="flex gap-1 items-center"><span className="text-[9px] text-gray-600 w-6">자간</span><input type="number" value={l.letter_spacing ?? 0} step={0.5} onChange={e => updTxt(l.id, { letter_spacing: parseFloat(e.target.value) })} className="w-10 bg-gray-900 text-white rounded px-1 py-0.5 text-[10px] border border-gray-700" /><span className="text-[9px] text-gray-600 w-6">행간</span><input type="number" value={l.line_spacing ?? 0} step={0.1} onChange={e => updTxt(l.id, { line_spacing: parseFloat(e.target.value) })} className="w-10 bg-gray-900 text-white rounded px-1 py-0.5 text-[10px] border border-gray-700" /><div className="flex gap-0.5 ml-auto">{(['left', 'center', 'right'] as const).map(a => (<button key={a} onClick={() => updTxt(l.id, { alignment: a })} className={`px-1 py-0.5 rounded text-[8px] ${(l.alignment || 'center') === a ? 'bg-indigo-600 text-white' : 'bg-gray-900 text-gray-500'}`}>{a === 'left' ? '◀' : a === 'center' ? '◆' : '▶'}</button>))}</div></div>
                  <Sl label="가로" value={l.scale_x ?? 1} min={0.1} max={2} step={0.05} fmt={v => `${Math.round(v * 100)}%`} onChange={v => updTxt(l.id, { scale_x: v })} />
                  <Sl label="세로" value={l.scale_y ?? 1} min={0.1} max={2} step={0.05} fmt={v => `${Math.round(v * 100)}%`} onChange={v => updTxt(l.id, { scale_y: v })} />
                  {/* 그림자 */}
                  <div className="bg-gray-900/50 rounded p-1.5"><div className="flex items-center gap-1 mb-1"><input type="checkbox" checked={l.shadow?.enabled ?? false} onChange={e => updTxt(l.id, { shadow: { ...(l.shadow || DEF_SHADOW), enabled: e.target.checked } })} className="w-3 h-3 accent-purple-600" /><span className="text-[9px] text-gray-500">그림자</span>{l.shadow?.enabled && <input type="color" value={l.shadow.color} onChange={e => updTxt(l.id, { shadow: { ...l.shadow!, color: e.target.value } })} className="w-4 h-4 rounded cursor-pointer" />}</div>
                    {l.shadow?.enabled && <div className="space-y-1"><Sl label="투명" value={l.shadow.alpha} min={0} max={1} step={0.05} fmt={v => `${Math.round(v * 100)}%`} onChange={v => updTxt(l.id, { shadow: { ...l.shadow!, alpha: v } })} /><Sl label="거리" value={l.shadow.distance} min={0} max={20} step={1} fmt={v => `${v}`} onChange={v => updTxt(l.id, { shadow: { ...l.shadow!, distance: v } })} /><Sl label="각도" value={l.shadow.angle} min={-180} max={180} step={5} fmt={v => `${v}°`} onChange={v => updTxt(l.id, { shadow: { ...l.shadow!, angle: v } })} /><Sl label="흐림" value={l.shadow.blur} min={0} max={10} step={0.25} fmt={v => `${v}`} onChange={v => updTxt(l.id, { shadow: { ...l.shadow!, blur: v } })} /></div>}
                  </div>
                  {/* 애니메이션 */}
                  <div className="flex gap-1 items-center"><span className="text-[9px] text-gray-500 w-6">등장</span><select value={l.animation_in?.type || 'none'} onChange={e => updTxt(l.id, { animation_in: { type: e.target.value as TextAnimation['type'], duration: l.animation_in?.duration || 3 } })} className="flex-1 bg-gray-900 text-white rounded px-1 py-0.5 text-[10px] border border-gray-700">{ANIM_TYPES.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}</select>{l.animation_in?.type !== 'none' && <><input type="number" value={l.animation_in?.duration || 3} step={0.5} min={0.5} max={10} onChange={e => updTxt(l.id, { animation_in: { ...l.animation_in!, duration: parseFloat(e.target.value) } })} className="w-8 bg-gray-900 text-white rounded px-1 py-0.5 text-[10px] border border-gray-700" /><span className="text-[8px] text-gray-600">초</span></>}</div>
                  <div className="flex gap-1 items-center"><span className="text-[9px] text-gray-500 w-6">퇴장</span><select value={l.animation_out?.type || 'none'} onChange={e => updTxt(l.id, { animation_out: { type: e.target.value as TextAnimation['type'], duration: l.animation_out?.duration || 2 } })} className="flex-1 bg-gray-900 text-white rounded px-1 py-0.5 text-[10px] border border-gray-700">{ANIM_TYPES.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}</select>{l.animation_out?.type !== 'none' && <><input type="number" value={l.animation_out?.duration || 2} step={0.5} min={0.5} max={10} onChange={e => updTxt(l.id, { animation_out: { ...l.animation_out!, duration: parseFloat(e.target.value) } })} className="w-8 bg-gray-900 text-white rounded px-1 py-0.5 text-[10px] border border-gray-700" /><span className="text-[8px] text-gray-600">초</span></>}</div>
                </div>
              )}
            </div>
          ))}
        </Section>

        {/* 자막 (SRT) */}
        <Section title="💬 자막" open={openSec.subtitle} onToggle={() => toggle('subtitle')} badge={subtitleEntries.length > 0 ? `${subtitleEntries.length}개` : '없음'}>
          {subtitleEntries.length === 0 ? (
            <p className="text-[10px] text-gray-600">노래만들기 → 트랙추가에서 SRT 파일을 업로드하세요</p>
          ) : (<>
            <p className="text-[10px] text-green-400 mb-1">✓ {subtitleEntries.length}개 자막 로드됨</p>
            <div className="flex gap-1 items-center mb-1">
              <button onClick={() => { setSubPreviewIdx(Math.max(0, subPreviewIdx - 1)); setPlayTime(subtitleEntries[Math.max(0, subPreviewIdx - 1)]?.start || 0) }} className="text-[10px] text-gray-500 px-1">◀</button>
              <span className="text-[10px] text-white">{subPreviewIdx + 1}/{subtitleEntries.length}</span>
              <button onClick={() => { setSubPreviewIdx(Math.min(subtitleEntries.length - 1, subPreviewIdx + 1)); setPlayTime(subtitleEntries[Math.min(subtitleEntries.length - 1, subPreviewIdx + 1)]?.start || 0) }} className="text-[10px] text-gray-500 px-1">▶</button>
              <span className="text-[9px] text-gray-600 ml-auto">{Math.floor(playTime / 60)}:{String(Math.floor(playTime % 60)).padStart(2, '0')}</span>
            </div>
            {playing && <p className="text-[9px] text-indigo-400">재생 중 — 타임코드에 맞춰 자막 자동 전환</p>}
            {/* 타임라인 자막 목록 (현재 자막 하이라이트) */}
            <div className="max-h-28 overflow-y-auto space-y-0.5 mb-2">
              {subtitleEntries.slice(Math.max(0, subPreviewIdx - 2), subPreviewIdx + 5).map((e, i) => {
                const realIdx = Math.max(0, subPreviewIdx - 2) + i
                const isCurrent = realIdx === subPreviewIdx
                const mm = Math.floor(e.start / 60)
                const ss = Math.floor(e.start % 60)
                return (
                  <div key={realIdx} onClick={() => { setSubPreviewIdx(realIdx); setPlayTime(e.start) }}
                    className={`flex gap-1.5 px-1.5 py-1 rounded cursor-pointer text-[10px] ${isCurrent ? 'bg-indigo-900/50 border border-indigo-700' : 'hover:bg-gray-800'}`}>
                    <span className="text-gray-600 shrink-0 w-8">{mm}:{String(ss).padStart(2,'0')}</span>
                    <span className={isCurrent ? 'text-white' : 'text-gray-500'}>{e.text.split('\n')[0].slice(0, 30)}</span>
                  </div>
                )
              })}
            </div>
            <p className="text-[9px] text-gray-600 mb-1">자막 스타일:</p>
            <select value={subStyle.font_family || FONTS[0].value} onChange={e => setSubStyle(s => ({ ...s, font_family: e.target.value }))} className="w-full bg-gray-800 text-white rounded px-1.5 py-0.5 text-[10px] border border-gray-700 mb-1">{FONTS.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}</select>
            <div className="flex gap-1 items-center"><input type="color" value={subStyle.color || '#FFFFFF'} onChange={e => setSubStyle(s => ({ ...s, color: e.target.value }))} className="w-5 h-5 rounded cursor-pointer" /><input type="number" value={subStyle.font_size || 15} onChange={e => setSubStyle(s => ({ ...s, font_size: parseInt(e.target.value) }))} className="w-10 bg-gray-800 text-white rounded px-1 py-0.5 text-[10px] border border-gray-700" /><span className="text-[8px] text-gray-600">px</span><button onClick={() => setSubStyle(s => ({ ...s, italic: !s.italic }))} className={`px-1 py-0.5 rounded text-[10px] italic ${subStyle.italic ? 'bg-purple-600 text-white' : 'bg-gray-800 text-gray-500'}`}>I</button></div>
          </>)}
        </Section>

        {/* 효과 */}
        <Section title="✨ 효과" open={openSec.effect} onToggle={() => toggle('effect')} badge={`${effects.filter(e => e.enabled).length}`}>
          {effects.map((eff, i) => (
            <div key={i} className="bg-gray-800 rounded p-1.5 space-y-1">
              <div className="flex items-center gap-1.5"><input type="checkbox" checked={eff.enabled} onChange={e => setEffects(p => p.map((ef, j) => j === i ? { ...ef, enabled: e.target.checked } : ef))} className="w-3 h-3 accent-purple-600" /><input value={eff.name} onChange={e => setEffects(p => p.map((ef, j) => j === i ? { ...ef, name: e.target.value } : ef))} className="flex-1 bg-gray-900 text-white rounded px-1.5 py-0.5 text-[10px] border border-gray-700" /><button onClick={() => setEffects(p => p.filter((_, j) => j !== i))} className="text-gray-600 hover:text-red-400 text-[10px]">✕</button></div>
              {Object.entries(eff.params).map(([k, v]) => (<Sl key={k} label={k} value={v as number} min={0} max={1} step={0.01} fmt={val => `${Math.round(val * 100)}%`} onChange={nv => setEffects(p => p.map((ef, j) => j === i ? { ...ef, params: { ...ef.params, [k]: nv } } : ef))} />))}
            </div>
          ))}
          <button onClick={() => setEffects(p => [...p, { enabled: true, name: '새 효과', effect_id: '', params: { animation: 0.5, speed: 0.15 } }])} className="text-[10px] text-purple-400 hover:text-purple-300">+ 효과 추가</button>
        </Section>

        {/* 템플릿 */}
        <Section title="📋 템플릿" open={openSec.template} onToggle={() => toggle('template')}>
          <div className="flex gap-1 mb-1"><input value={tplName} onChange={e => setTplName(e.target.value)} placeholder="이름..." className="flex-1 bg-gray-800 text-white rounded px-2 py-1 text-[10px] border border-gray-700" /><button disabled={!tplName.trim() || !project.channel_id} onClick={async () => { if (!project.channel_id) return; await api.channels.saveTemplate(project.channel_id, { name: tplName.trim(), waveform_layer: wf, text_layers: texts.map(({ id: _, ...r }) => r), effect_layers: effects, subtitle_style: subStyle as LayerTemplate['subtitle_style'] }); setTemplates(await api.channels.listTemplates(project.channel_id)); setTplName('') }} className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white px-2 py-1 rounded text-[10px]">💾</button></div>
          {templates.map(tpl => (
            <div key={tpl.name} className="flex items-center gap-1 bg-gray-800 rounded px-2 py-1 mb-1">
              <span className="flex-1 text-[10px] text-white truncate">{tpl.name}</span>
              <button onClick={() => { if (tpl.waveform_layer) setWf(mgWf(tpl.waveform_layer)); if (tpl.text_layers) setTexts(tpl.text_layers.map(t => mgTxt({ ...t, id: crypto.randomUUID(), text: t.text || '' }))); if (tpl.effect_layers) setEffects(tpl.effect_layers); if (tpl.subtitle_style) setSubStyle(tpl.subtitle_style as Partial<TextLayerConfig>) }} className="text-[10px] text-indigo-400 hover:text-indigo-300 px-1.5 rounded border border-indigo-800">적용</button>
              <button onClick={async () => { if (!project.channel_id) return; await api.channels.deleteTemplate(project.channel_id, tpl.name); setTemplates(p => p.filter(t => t.name !== tpl.name)) }} className="text-gray-600 hover:text-red-400 text-[10px]">✕</button>
            </div>
          ))}
        </Section>
      </div>

      {/* ═══ 오른쪽 캔버스 ═══ */}
      <div className="flex-1">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-bold text-white">🎬 레이어 미리보기</h2>
          <div className="flex gap-2">
            <button onClick={() => { if (playing) { setPlaying(false) } else { setPlayTime(0); setSubPreviewIdx(0); setPlaying(true) } }} className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${playing ? 'bg-red-700 text-white' : 'bg-gray-700 text-gray-300'}`}>{playing ? '⏸ 정지' : '▶ 미리보기'}</button>
            <button onClick={save} disabled={saving} className="bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white px-4 py-1.5 rounded-lg text-xs font-semibold">{saving ? '저장 중...' : '💾 저장'}</button>
          </div>
        </div>

        <div ref={boxRef} className="relative rounded-xl overflow-hidden border border-gray-800 select-none" style={{ width: CW, height: CH, background: '#000' }} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp}>
          {bgUrl ? <img src={bgUrl} alt="" className="absolute inset-0 w-full h-full object-cover" draggable={false} /> : <div className="absolute inset-0 flex items-center justify-center text-gray-700 text-sm">배경 이미지 없음</div>}
          <canvas ref={fxRef} width={CW} height={CH} className="absolute inset-0 pointer-events-none" />
          {wf.enabled && <>
            <canvas ref={cvRef} width={CW} height={CH} className="absolute inset-0 pointer-events-none" />
            {wf.style !== 'circle' && <div className="absolute border border-dashed border-white/20" style={{ left: wf.position_x * CW - wfNW / 2, top: wf.position_y * CH - wfNH / 2, width: wfNW, height: wfNH }}><div className="absolute inset-0 cursor-move" onMouseDown={startDrag('move-wf', 'wf')} />{['nw', 'ne', 'sw', 'se'].map(c => (<div key={c} className={`absolute w-2.5 h-2.5 bg-white/40 hover:bg-white/80 rounded-sm ${c.includes('n') ? 'top-0' : 'bottom-0'} ${c.includes('w') ? 'left-0' : 'right-0'} cursor-nwse-resize`} style={{ transform: 'translate(-50%,-50%)' }} onMouseDown={startDrag('resize-wf', 'wf')} />))}</div>}
            {wf.style === 'circle' && <div className="absolute w-6 h-6 cursor-move rounded-full border border-white/30 hover:border-white/60 bg-white/10 flex items-center justify-center" style={{ left: `${wf.position_x * 100}%`, top: `${wf.position_y * 100}%`, transform: 'translate(-50%,-50%)' }} onMouseDown={startDrag('move-wf', 'wf')}><span className="text-[7px] text-white/40">+</span></div>}
          </>}
          {/* 텍스트 */}
          {texts.map(l => (
            <div key={l.id} className={`absolute group ${dragId === l.id ? 'ring-2 ring-purple-400' : 'hover:ring-1 hover:ring-white/20'}`}
              style={{ left: `${l.position_x * 100}%`, top: `${l.position_y * 100}%`, transform: `translate(-50%,-50%) scaleX(${l.scale_x ?? 1}) scaleY(${l.scale_y ?? 1})`, fontSize: `${l.font_size * S}px`, fontFamily: l.font_family, color: l.color, opacity: l.alpha ?? 1, fontWeight: l.bold ? 'bold' : 'normal', fontStyle: l.italic ? 'italic' : 'normal', textShadow: l.shadow?.enabled ? `${Math.cos((l.shadow.angle || 0) * Math.PI / 180) * (l.shadow.distance || 5) * S}px ${-Math.sin((l.shadow.angle || 0) * Math.PI / 180) * (l.shadow.distance || 5) * S}px ${(l.shadow.blur || 2) * S}px rgba(0,0,0,${l.shadow.alpha || 0.5})` : '1px 1px 3px rgba(0,0,0,0.5)', whiteSpace: 'pre-wrap', userSelect: 'none', textAlign: l.alignment || 'center' }}>
              <div className="cursor-move" onMouseDown={startDrag('move-text', l.id)} onDoubleClick={() => setEditId(editId === l.id ? null : l.id)}>{l.text}</div>
              <div className="absolute -bottom-1 -right-1 w-2.5 h-2.5 bg-purple-500/50 hover:bg-purple-400 rounded-sm cursor-se-resize opacity-0 group-hover:opacity-100" onMouseDown={startDrag('resize-text', l.id)} />
            </div>
          ))}
          {/* 자막 미리보기 — 재생 중엔 타임코드 맞을 때만 표시 */}
          {subPreview && (!playing || (playTime >= subPreview.start && playTime <= subPreview.end)) && (
            <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none text-center" style={{ fontSize: `${(subStyle.font_size || 15) * S * (subStyle.scale_x ?? 0.325)}px`, fontFamily: subStyle.font_family || FONTS[1].value, color: subStyle.color || '#FFFFFF', fontStyle: subStyle.italic ? 'italic' : 'normal', opacity: 0.9, textShadow: '2px 2px 4px rgba(0,0,0,0.5)', whiteSpace: 'pre-wrap' }}>
              {subPreview.text}
            </div>
          )}
        </div>
        <p className="text-[9px] text-gray-700 mt-2 text-center">드래그=이동 · 코너=리사이즈 · 더블클릭=편집</p>
      </div>
    </div>
  )
}
