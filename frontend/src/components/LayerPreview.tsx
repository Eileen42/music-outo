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
  { value: '"Palatino Linotype"', label: 'Palatino Linotype Bold Italic' },
  { value: 'Pretendard, sans-serif', label: 'Pretendard' },
  { value: '"Noto Sans KR", sans-serif', label: 'Noto Sans KR' },
  { value: '"Noto Serif KR", serif', label: 'Noto Serif (명조)' },
  { value: 'Arial, sans-serif', label: 'Arial' },
  { value: 'Georgia, serif', label: 'Georgia' },
  { value: '"Courier New", monospace', label: 'Courier New' },
  { value: 'Impact, sans-serif', label: 'Impact' },
  { value: '"Segoe UI", sans-serif', label: 'Segoe UI' },
  { value: '"Malgun Gothic", sans-serif', label: '맑은 고딕' },
  { value: '"Times New Roman", serif', label: 'Times New Roman' },
]

const ANIM_TYPES = [
  { value: 'none', label: '없음' },
  { value: 'fade_in', label: '페이드 인' },
  { value: 'fade_out', label: '페이드 아웃' },
  { value: 'slide_up', label: '슬라이드 업' },
  { value: 'slide_down', label: '슬라이드 다운' },
  { value: 'typewriter', label: '타이핑' },
]

const DEF_SHADOW: TextShadow = { enabled: false, color: '#000000', alpha: 0.36, angle: -45, distance: 5, blur: 1.75 }
const DEF_ANIM: TextAnimation = { type: 'none', duration: 0 }

function defaultText(): Omit<TextLayerConfig, 'id'> {
  return {
    text: '', font_size: 36, font_family: FONTS[0].value, color: '#FFFFFF', alpha: 1,
    position_x: 0.5, position_y: 0.1, scale_x: 1, scale_y: 1,
    bold: false, italic: false, letter_spacing: 0, line_spacing: 0,
    alignment: 'center', shadow: { ...DEF_SHADOW }, animation_in: { ...DEF_ANIM }, animation_out: { ...DEF_ANIM },
    role: 'custom',
  }
}

function migrateText(t: Partial<TextLayerConfig> & { id: string; text: string }): TextLayerConfig {
  return {
    ...defaultText(),
    ...t,
    font_family: t.font_family || FONTS[0].value,
    shadow: { ...DEF_SHADOW, ...(t.shadow || {}) },
    animation_in: { ...DEF_ANIM, ...(t.animation_in || {}) },
    animation_out: { ...DEF_ANIM, ...(t.animation_out || {}) },
    alpha: t.alpha ?? 1, scale_x: t.scale_x ?? 1, scale_y: t.scale_y ?? 1,
    italic: t.italic ?? false, letter_spacing: t.letter_spacing ?? 0,
    line_spacing: t.line_spacing ?? 0, alignment: t.alignment ?? 'center',
    role: t.role ?? 'custom',
  }
}

const DEF: WaveformLayerConfig = {
  enabled: true, style: 'bar', color: '#FFFFFF', opacity: 0.8,
  position_x: 0.5, position_y: 0.7,
  bar_count: 60, bar_width: 4, bar_gap: 2, bar_height: 120, bar_min: 0.1,
  bar_align: 'bottom', scale: 1.0, circle_radius: 0.12,
}
const CW = 768, CH = 432, S = CW / 1920

function mg(s: Partial<WaveformLayerConfig> | null): WaveformLayerConfig { return { ...DEF, ...(s || {}) } }

// 가우시안 엔벨로프: 가운데 1.0, 양끝 ~0.2
function bellEnvelope(i: number, count: number): number {
  const x = (i / (count - 1)) * 2 - 1 // -1 ~ 1
  return 0.2 + 0.8 * Math.exp(-3 * x * x)
}

// 반딧불이 파티클
interface Particle { x: number; y: number; vx: number; vy: number; size: number; alpha: number; phase: number }
function initParticles(n: number): Particle[] {
  return Array.from({ length: n }, () => ({
    x: Math.random(), y: Math.random(),
    vx: (Math.random() - 0.5) * 0.0008, vy: (Math.random() - 0.5) * 0.0006,
    size: Math.random() * 3 + 1, alpha: Math.random(), phase: Math.random() * Math.PI * 2,
  }))
}

export default function LayerPreview({ project, onRefresh }: Props) {
  const [saving, setSaving] = useState(false)
  const layers = project.layers || { background_video: null, waveform_layer: null, text_layers: [], effect_layers: [] }
  const [wf, setWf] = useState<WaveformLayerConfig>(mg(layers.waveform_layer))
  const [texts, setTexts] = useState<TextLayerConfig[]>(
    (layers.text_layers || []).map(t => migrateText(t as TextLayerConfig))
  )
  const [effects, setEffects] = useState<EffectLayerConfig[]>(layers.effect_layers || [])
  const [newText, setNewText] = useState('')
  const [addingText, setAddingText] = useState(false)
  const [editId, setEditId] = useState<string | null>(null)
  const [playing, setPlaying] = useState(false)
  const [templates, setTemplates] = useState<LayerTemplate[]>([])
  const [tplName, setTplName] = useState('')

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
  const particlesRef = useRef<Particle[]>(initParticles(40))

  const bgUrl = storageUrl(project.images?.background || project.images?.thumbnail || '')

  useEffect(() => {
    if (project.channel_id) api.channels.listTemplates(project.channel_id).then(setTemplates).catch(() => {})
  }, [project.channel_id])

  // ── 파형 크기 ──
  const wfNW = wf.bar_count * ((wf.bar_width + wf.bar_gap) * S) * wf.scale
  const wfNH = wf.bar_height * S * wf.scale
  const wfLeft = wf.position_x * CW - wfNW / 2
  const wfTop = wf.position_y * CH - wfNH / 2

  // ── 파형 그리기 (가우시안 엔벨로프) ──
  const drawWf = useCallback(() => {
    const cv = cvRef.current
    if (!cv || !wf.enabled) { if (cv) { cv.getContext('2d')?.clearRect(0, 0, CW, CH) } return }
    const ctx = cv.getContext('2d')!
    cv.width = CW; cv.height = CH; ctx.clearRect(0, 0, CW, CH)

    const count = wf.bar_count || 60
    const sc = wf.scale * S
    const bw = wf.bar_width * sc, gap = wf.bar_gap * sc, maxH = wf.bar_height * sc
    const cx = wf.position_x * CW, cy = wf.position_y * CH
    const totalW = count * (bw + gap), startX = cx - totalW / 2

    ctx.globalAlpha = wf.opacity; ctx.fillStyle = wf.color

    if (barsRef.current.length !== count) {
      barsRef.current = Array.from({ length: count }, () => Math.random())
      targRef.current = Array.from({ length: count }, () => Math.random())
    }
    for (let i = 0; i < count; i++) barsRef.current[i] += (targRef.current[i] - barsRef.current[i]) * 0.08
    const bmin = wf.bar_min ?? 0.1
    tickRef.current++
    if (tickRef.current % 6 === 0)
      for (let i = 0; i < count; i++) targRef.current[i] = Math.random() * (1 - bmin) + bmin

    if (wf.style === 'circle') {
      const r = CH * (wf.circle_radius || 0.12) * wf.scale
      const cbw = Math.max(2, bw * 0.8)
      for (let i = 0; i < count; i++) {
        const env = bellEnvelope(i, count)
        const h = barsRef.current[i] * maxH * env
        const a = (i / count) * Math.PI * 2 - Math.PI / 2
        ctx.beginPath()
        ctx.moveTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r)
        ctx.lineTo(cx + Math.cos(a) * (r + h), cy + Math.sin(a) * (r + h))
        ctx.lineWidth = cbw; ctx.lineCap = 'round'; ctx.strokeStyle = wf.color; ctx.stroke()
      }
    } else {
      for (let i = 0; i < count; i++) {
        const env = bellEnvelope(i, count)
        const h = barsRef.current[i] * maxH * env
        const x = startX + i * (bw + gap)
        if (wf.bar_align === 'center') ctx.fillRect(x, cy - h / 2, bw, h)
        else if (wf.bar_align === 'top') ctx.fillRect(x, cy, bw, h)
        else ctx.fillRect(x, cy - h, bw, h)
      }
    }
    ctx.globalAlpha = 1
  }, [wf])

  // ── 반딧불이 효과 그리기 ──
  const drawFx = useCallback(() => {
    const cv = fxRef.current
    if (!cv) return
    const ctx = cv.getContext('2d')!
    cv.width = CW; cv.height = CH; ctx.clearRect(0, 0, CW, CH)

    const hasFirefly = effects.some(e => e.enabled && e.name.includes('반딧불'))
    if (!hasFirefly) return

    const speed = effects.find(e => e.name.includes('반딧불'))?.params?.speed ?? 0.14
    const particles = particlesRef.current
    for (const p of particles) {
      p.x += p.vx * (1 + speed * 5); p.y += p.vy * (1 + speed * 5)
      p.phase += 0.02
      if (p.x < 0 || p.x > 1) p.vx *= -1
      if (p.y < 0 || p.y > 1) p.vy *= -1
      const flicker = 0.3 + 0.7 * (0.5 + 0.5 * Math.sin(p.phase))
      ctx.beginPath()
      ctx.arc(p.x * CW, p.y * CH, p.size, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(255, 255, 180, ${flicker * 0.6})`
      ctx.fill()
      // glow
      ctx.beginPath()
      ctx.arc(p.x * CW, p.y * CH, p.size * 3, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(255, 255, 150, ${flicker * 0.15})`
      ctx.fill()
    }
  }, [effects])

  useEffect(() => {
    if (!playing) { drawWf(); drawFx(); return }
    let on = true
    const tick = () => { if (!on) return; drawWf(); drawFx(); animRef.current = requestAnimationFrame(tick) }
    tick()
    return () => { on = false; cancelAnimationFrame(animRef.current) }
  }, [playing, drawWf, drawFx])
  useEffect(() => { drawWf(); drawFx() }, [drawWf, drawFx])

  // ── 드래그 ──
  const startDrag = (mode: DragMode, id: string) => (e: React.MouseEvent) => {
    e.preventDefault(); e.stopPropagation()
    setDragMode(mode); setDragId(id)
    const r = boxRef.current!.getBoundingClientRect()
    const layer = texts.find(t => t.id === id)
    dragStartRef.current = { mx: e.clientX, my: e.clientY, origSize: layer?.font_size || 36 }
  }
  const onMove = useCallback((e: React.MouseEvent) => {
    if (!dragMode || !boxRef.current) return
    const r = boxRef.current.getBoundingClientRect()
    const x = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width))
    const y = Math.max(0, Math.min(1, (e.clientY - r.top) / r.height))

    if (dragMode === 'move-wf') setWf(w => ({ ...w, position_x: x, position_y: y }))
    else if (dragMode === 'move-text') setTexts(p => p.map(t => t.id === dragId ? { ...t, position_x: x, position_y: y } : t))
    else if (dragMode === 'resize-wf') {
      const dx = Math.abs(x - wf.position_x) * 2
      const origW = (wf.bar_count * (wf.bar_width + wf.bar_gap) * S) / CW
      if (origW > 0) setWf(w => ({ ...w, scale: Math.max(0.2, Math.min(5, dx / origW)) }))
    } else if (dragMode === 'resize-text' && dragStartRef.current) {
      const dy = e.clientY - dragStartRef.current.my
      const newSize = Math.max(12, Math.min(200, dragStartRef.current.origSize - dy * 0.5))
      setTexts(p => p.map(t => t.id === dragId ? { ...t, font_size: Math.round(newSize) } : t))
    }
  }, [dragMode, dragId, wf])
  const onUp = () => { setDragMode(null); setDragId(null); dragStartRef.current = null }

  // ── 저장 ──
  const save = async () => {
    setSaving(true)
    try { await api.layers.update(project.id, { ...layers, waveform_layer: wf, text_layers: texts, effect_layers: effects }); await onRefresh() }
    finally { setSaving(false) }
  }
  const addTxt = async () => {
    if (!newText.trim()) return; setAddingText(true)
    try {
      await api.layers.addText(project.id, { ...defaultText(), text: newText.trim() })
      setNewText(''); await onRefresh()
      const u = await api.layers.get(project.id)
      setTexts((u.text_layers || []).map((t: TextLayerConfig) => ({ ...t, font_family: t.font_family || FONTS[0].value })))
    } finally { setAddingText(false) }
  }
  const delTxt = async (id: string) => { await api.layers.deleteText(project.id, id); setTexts(p => p.filter(t => t.id !== id)); await onRefresh() }
  const updTxt = (id: string, u: Partial<TextLayerConfig>) => setTexts(p => p.map(t => t.id === id ? { ...t, ...u } : t))

  const Sl = ({ label, value, min, max, step, fmt, onChange }: {
    label: string; value: number; min: number; max: number; step: number; fmt?: (v: number) => string; onChange: (v: number) => void
  }) => (
    <div>
      <div className="flex justify-between text-[10px] text-gray-500 mb-0.5"><span>{label}</span><span>{fmt ? fmt(value) : value}</span></div>
      <input type="range" min={min} max={max} step={step} value={value} onChange={e => onChange(parseFloat(e.target.value))} className="w-full accent-purple-600 h-1" />
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
        style={{ width: CW, height: CH, background: '#000' }} onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp}>
        {bgUrl ? <img src={bgUrl} alt="" className="absolute inset-0 w-full h-full object-cover" draggable={false} /> : <div className="absolute inset-0 flex items-center justify-center text-gray-700 text-sm">배경 이미지 없음</div>}
        {/* 효과 캔버스 (반딧불이) */}
        <canvas ref={fxRef} width={CW} height={CH} className="absolute inset-0 pointer-events-none" />
        {/* 파형 캔버스 */}
        {wf.enabled && (
          <>
            <canvas ref={cvRef} width={CW} height={CH} className="absolute inset-0 pointer-events-none" />
            {wf.style !== 'circle' && (
              <div className="absolute border border-dashed border-white/20 hover:border-white/40"
                style={{ left: wfLeft, top: wfTop, width: wfNW, height: wfNH }}>
                <div className="absolute inset-0 cursor-move" onMouseDown={startDrag('move-wf', 'wf')} />
                {['nw','ne','sw','se'].map(c => (
                  <div key={c} className={`absolute w-3 h-3 bg-white/40 hover:bg-white/80 border border-white/60 rounded-sm ${c.includes('n')?'top-0':'bottom-0'} ${c.includes('w')?'left-0':'right-0'} ${c==='nw'||c==='se'?'cursor-nwse-resize':'cursor-nesw-resize'}`}
                    style={{transform:'translate(-50%,-50%)'}} onMouseDown={startDrag('resize-wf','wf')} />
                ))}
              </div>
            )}
            {wf.style === 'circle' && (
              <div className="absolute w-8 h-8 cursor-move rounded-full border-2 border-white/30 hover:border-white/60 bg-white/10 flex items-center justify-center"
                style={{left:`${wf.position_x*100}%`,top:`${wf.position_y*100}%`,transform:'translate(-50%,-50%)'}} onMouseDown={startDrag('move-wf','wf')}>
                <span className="text-[8px] text-white/50">+</span></div>
            )}
          </>
        )}
        {/* 텍스트 레이어 + 리사이즈 핸들 */}
        {texts.map(l => (
          <div key={l.id} className={`absolute group ${dragId===l.id?'ring-2 ring-purple-400':'hover:ring-1 hover:ring-white/30'}`}
            style={{left:`${l.position_x*100}%`,top:`${l.position_y*100}%`,transform:`translate(-50%,-50%) scaleX(${l.scale_x??1}) scaleY(${l.scale_y??1})`,
              fontSize:`${l.font_size*S}px`,fontFamily:l.font_family||FONTS[0].value,
              color:l.color,opacity:l.alpha??1,fontWeight:l.bold?'bold':'normal',fontStyle:l.italic?'italic':'normal',
              letterSpacing:`${(l.letter_spacing||0)*S}px`,lineHeight:l.line_spacing?`${1+l.line_spacing}`:undefined,
              textAlign:l.alignment||'center',
              textShadow:l.shadow?.enabled?`${Math.cos((l.shadow.angle||0)*Math.PI/180)*(l.shadow.distance||5)*S}px ${-Math.sin((l.shadow.angle||0)*Math.PI/180)*(l.shadow.distance||5)*S}px ${(l.shadow.blur||2)*S}px rgba(0,0,0,${l.shadow.alpha||0.5})`:'2px 2px 4px rgba(0,0,0,0.5)',
              whiteSpace:'pre-wrap',userSelect:'none',textAlignLast:l.alignment||'center'}}>
            <div className="cursor-move" onMouseDown={startDrag('move-text',l.id)} onDoubleClick={()=>setEditId(editId===l.id?null:l.id)}>{l.text}</div>
            {/* 리사이즈 핸들 (우하단) */}
            <div className="absolute -bottom-1 -right-1 w-3 h-3 bg-purple-500/60 hover:bg-purple-400 rounded-sm cursor-se-resize opacity-0 group-hover:opacity-100 transition-opacity"
              onMouseDown={startDrag('resize-text',l.id)} />
          </div>
        ))}
      </div>

      {/* ── 컨트롤 3열 ── */}
      <div className="grid grid-cols-3 gap-3">
        {/* 파형 */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-3">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">파형</h3>
            <input type="checkbox" checked={wf.enabled} onChange={e=>setWf(w=>({...w,enabled:e.target.checked}))} className="w-3.5 h-3.5 accent-purple-600" />
          </div>
          {wf.enabled && (
            <div className="space-y-2">
              <div className="flex gap-1">
                {(['bar','line','circle'] as const).map(s=>(
                  <button key={s} onClick={()=>setWf(w=>({...w,style:s}))} className={`flex-1 py-1 rounded text-[10px] font-medium ${wf.style===s?'bg-purple-600 text-white':'bg-gray-800 text-gray-500'}`}>
                    {s==='bar'?'막대':s==='line'?'라인':'원형'}</button>))}
              </div>
              {wf.style!=='circle'&&(
                <div className="flex gap-1">
                  {(['bottom','center','top'] as const).map(a=>(
                    <button key={a} onClick={()=>setWf(w=>({...w,bar_align:a}))} className={`flex-1 py-0.5 rounded text-[10px] ${wf.bar_align===a?'bg-indigo-600 text-white':'bg-gray-800 text-gray-500'}`}>
                      {a==='bottom'?'바닥':a==='center'?'중간':'위'}</button>))}
                </div>
              )}
              <div className="flex items-center gap-1.5">
                <input type="color" value={wf.color} onChange={e=>setWf(w=>({...w,color:e.target.value}))} className="w-6 h-6 rounded bg-gray-800 border border-gray-700 cursor-pointer" />
                <input value={wf.color} onChange={e=>setWf(w=>({...w,color:e.target.value}))} className="flex-1 bg-gray-800 text-white rounded px-1.5 py-0.5 text-[10px] border border-gray-700 font-mono" />
              </div>
              <Sl label="크기" value={wf.scale} min={0.2} max={3} step={0.1} fmt={v=>`${Math.round(v*100)}%`} onChange={v=>setWf(w=>({...w,scale:v}))} />
              <Sl label="개수" value={wf.bar_count} min={10} max={200} step={5} fmt={v=>`${v}`} onChange={v=>{setWf(w=>({...w,bar_count:v}));barsRef.current=[];targRef.current=[]}} />
              <Sl label="너비" value={wf.bar_width} min={1} max={20} step={1} fmt={v=>`${v}px`} onChange={v=>setWf(w=>({...w,bar_width:v}))} />
              <Sl label="간격" value={wf.bar_gap} min={0} max={15} step={1} fmt={v=>`${v}px`} onChange={v=>setWf(w=>({...w,bar_gap:v}))} />
              <Sl label="높이" value={wf.bar_height} min={20} max={400} step={10} fmt={v=>`${v}px`} onChange={v=>setWf(w=>({...w,bar_height:v}))} />
              <Sl label="편차" value={wf.bar_min??0.1} min={0} max={0.95} step={0.05} fmt={v=>v>=0.9?'균일':`${Math.round(v*100)}%`} onChange={v=>setWf(w=>({...w,bar_min:v}))} />
              <Sl label="투명도" value={wf.opacity} min={0} max={1} step={0.05} fmt={v=>`${Math.round(v*100)}%`} onChange={v=>setWf(w=>({...w,opacity:v}))} />
              {wf.style==='circle'&&<Sl label="반지름" value={wf.circle_radius} min={0.05} max={0.3} step={0.01} fmt={v=>`${Math.round(v*100)}%`} onChange={v=>setWf(w=>({...w,circle_radius:v}))} />}
            </div>
          )}
        </div>

        {/* 텍스트 */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-3">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-2">텍스트</h3>
          <div className="flex gap-1 mb-2">
            <input value={newText} onChange={e=>setNewText(e.target.value)} placeholder="텍스트..."
              className="flex-1 bg-gray-800 text-white rounded px-2 py-1 text-xs border border-gray-700 focus:outline-none focus:border-purple-500"
              onKeyDown={e=>{if(e.key==='Enter')addTxt()}} />
            <button onClick={addTxt} disabled={addingText||!newText.trim()} className="bg-purple-600 hover:bg-purple-500 disabled:opacity-40 text-white px-2 py-1 rounded text-xs font-semibold">+</button>
          </div>
          <div className="space-y-1.5 max-h-60 overflow-y-auto">
            {texts.length===0&&<div className="text-center py-3 text-gray-700 text-[10px]">드래그=이동 · 우하단 핸들=크기 · 더블클릭=편집</div>}
            {texts.map(l=>(
              <div key={l.id} className="bg-gray-800 rounded-lg p-2 space-y-1.5">
                <div className="flex items-center gap-1.5">
                  <div className="w-2.5 h-2.5 rounded shrink-0 border border-gray-600" style={{backgroundColor:l.color}} />
                  <span className="flex-1 text-[11px] text-white truncate" style={{fontFamily:l.font_family}}>{l.text}</span>
                  <button onClick={()=>setEditId(editId===l.id?null:l.id)} className="text-gray-500 hover:text-gray-300 text-[10px]">{editId===l.id?'▲':'✏️'}</button>
                  <button onClick={()=>delTxt(l.id)} className="text-gray-600 hover:text-red-400 text-[10px]">✕</button>
                </div>
                {editId===l.id&&(
                  <div className="space-y-1.5 pt-1 border-t border-gray-700">
                    <input value={l.text} onChange={e=>updTxt(l.id,{text:e.target.value})} className="w-full bg-gray-900 text-white rounded px-2 py-1 text-xs border border-gray-700" />
                    {/* 폰트 + 역할 */}
                    <div className="flex gap-1">
                      <select value={l.font_family||FONTS[0].value} onChange={e=>updTxt(l.id,{font_family:e.target.value})}
                        className="flex-1 bg-gray-900 text-white rounded px-1.5 py-0.5 text-[10px] border border-gray-700">
                        {FONTS.map(f=><option key={f.value} value={f.value}>{f.label}</option>)}</select>
                      <select value={l.role||'custom'} onChange={e=>updTxt(l.id,{role:e.target.value as TextLayerConfig['role']})}
                        className="w-16 bg-gray-900 text-white rounded px-1 py-0.5 text-[10px] border border-gray-700">
                        <option value="title">제목</option><option value="subtitle">자막</option>
                        <option value="description">설명</option><option value="custom">커스텀</option></select>
                    </div>
                    {/* 색상 + 크기 + B/I */}
                    <div className="flex gap-1 items-center flex-wrap">
                      <input type="color" value={l.color} onChange={e=>updTxt(l.id,{color:e.target.value})} className="w-5 h-5 rounded cursor-pointer bg-gray-900 border border-gray-700" />
                      <input type="number" value={l.font_size} onChange={e=>updTxt(l.id,{font_size:parseInt(e.target.value)||24})}
                        className="w-11 bg-gray-900 text-white rounded px-1 py-0.5 text-[10px] border border-gray-700" min={8} max={200} />
                      <span className="text-[9px] text-gray-600">px</span>
                      <button onClick={()=>updTxt(l.id,{bold:!l.bold})}
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${l.bold?'bg-purple-600 text-white':'bg-gray-900 text-gray-500 border border-gray-700'}`}>B</button>
                      <button onClick={()=>updTxt(l.id,{italic:!l.italic})}
                        className={`px-1.5 py-0.5 rounded text-[10px] italic ${l.italic?'bg-purple-600 text-white':'bg-gray-900 text-gray-500 border border-gray-700'}`}>I</button>
                      <div className="flex items-center gap-0.5">
                        <span className="text-[9px] text-gray-600">투명</span>
                        <input type="range" min={0} max={1} step={0.05} value={l.alpha??1}
                          onChange={e=>updTxt(l.id,{alpha:parseFloat(e.target.value)})} className="w-12 accent-purple-600 h-1" />
                      </div>
                    </div>
                    {/* 간격 + 정렬 */}
                    <div className="flex gap-1 items-center">
                      <span className="text-[9px] text-gray-600 w-8">자간</span>
                      <input type="number" value={l.letter_spacing??0} step={0.5}
                        onChange={e=>updTxt(l.id,{letter_spacing:parseFloat(e.target.value)})}
                        className="w-12 bg-gray-900 text-white rounded px-1 py-0.5 text-[10px] border border-gray-700" />
                      <span className="text-[9px] text-gray-600 w-8 ml-1">행간</span>
                      <input type="number" value={l.line_spacing??0} step={0.1}
                        onChange={e=>updTxt(l.id,{line_spacing:parseFloat(e.target.value)})}
                        className="w-12 bg-gray-900 text-white rounded px-1 py-0.5 text-[10px] border border-gray-700" />
                      <div className="flex gap-0.5 ml-auto">
                        {(['left','center','right'] as const).map(a=>(
                          <button key={a} onClick={()=>updTxt(l.id,{alignment:a})}
                            className={`px-1 py-0.5 rounded text-[9px] ${(l.alignment||'center')===a?'bg-indigo-600 text-white':'bg-gray-900 text-gray-500 border border-gray-700'}`}>
                            {a==='left'?'◀':a==='center'?'◆':'▶'}</button>))}
                      </div>
                    </div>
                    {/* 그림자 */}
                    <div className="bg-gray-900/50 rounded p-1.5">
                      <div className="flex items-center gap-1.5 mb-1">
                        <input type="checkbox" checked={l.shadow?.enabled??false}
                          onChange={e=>updTxt(l.id,{shadow:{...(l.shadow||DEF_SHADOW),enabled:e.target.checked}})}
                          className="w-3 h-3 accent-purple-600" />
                        <span className="text-[9px] text-gray-500">그림자</span>
                        {l.shadow?.enabled && <>
                          <input type="color" value={l.shadow?.color||'#000000'}
                            onChange={e=>updTxt(l.id,{shadow:{...l.shadow!,color:e.target.value}})}
                            className="w-4 h-4 rounded cursor-pointer" />
                        </>}
                      </div>
                      {l.shadow?.enabled && (
                        <div className="grid grid-cols-2 gap-1 text-[9px]">
                          <div className="flex items-center gap-1"><span className="text-gray-600 w-6">투명</span>
                            <input type="range" min={0} max={1} step={0.05} value={l.shadow.alpha}
                              onChange={e=>updTxt(l.id,{shadow:{...l.shadow!,alpha:parseFloat(e.target.value)}})} className="flex-1 accent-purple-600 h-1" /></div>
                          <div className="flex items-center gap-1"><span className="text-gray-600 w-6">거리</span>
                            <input type="range" min={0} max={20} step={1} value={l.shadow.distance}
                              onChange={e=>updTxt(l.id,{shadow:{...l.shadow!,distance:parseFloat(e.target.value)}})} className="flex-1 accent-purple-600 h-1" /></div>
                          <div className="flex items-center gap-1"><span className="text-gray-600 w-6">각도</span>
                            <input type="range" min={-180} max={180} step={5} value={l.shadow.angle}
                              onChange={e=>updTxt(l.id,{shadow:{...l.shadow!,angle:parseFloat(e.target.value)}})} className="flex-1 accent-purple-600 h-1" /></div>
                          <div className="flex items-center gap-1"><span className="text-gray-600 w-6">흐림</span>
                            <input type="range" min={0} max={10} step={0.25} value={l.shadow.blur}
                              onChange={e=>updTxt(l.id,{shadow:{...l.shadow!,blur:parseFloat(e.target.value)}})} className="flex-1 accent-purple-600 h-1" /></div>
                        </div>
                      )}
                    </div>
                    {/* 애니메이션 */}
                    <div className="flex gap-1 items-center">
                      <span className="text-[9px] text-gray-600">등장</span>
                      <select value={l.animation_in?.type||'none'} onChange={e=>updTxt(l.id,{animation_in:{type:e.target.value as TextAnimation['type'],duration:l.animation_in?.duration||3}})}
                        className="flex-1 bg-gray-900 text-white rounded px-1 py-0.5 text-[10px] border border-gray-700">
                        {ANIM_TYPES.map(a=><option key={a.value} value={a.value}>{a.label}</option>)}</select>
                      {l.animation_in?.type!=='none'&&<input type="number" value={l.animation_in?.duration||3} step={0.5} min={0.5} max={10}
                        onChange={e=>updTxt(l.id,{animation_in:{...l.animation_in!,duration:parseFloat(e.target.value)}})}
                        className="w-10 bg-gray-900 text-white rounded px-1 py-0.5 text-[10px] border border-gray-700" />}
                      {l.animation_in?.type!=='none'&&<span className="text-[9px] text-gray-600">초</span>}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* 효과 */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-3">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">효과</h3>
            <button onClick={()=>setEffects(p=>[...p,{enabled:true,name:'새 효과',effect_id:'',params:{animation:0.5,speed:0.15}}])}
              className="text-[10px] text-purple-400 hover:text-purple-300">+ 추가</button>
          </div>
          {effects.length===0&&<div className="text-center py-3 text-gray-700 text-[10px]">효과 없음</div>}
          {effects.map((eff,i)=>(
            <div key={i} className="bg-gray-800 rounded-lg p-2 mb-1.5 space-y-1.5">
              <div className="flex items-center gap-2">
                <input type="checkbox" checked={eff.enabled} onChange={e=>setEffects(p=>p.map((ef,j)=>j===i?{...ef,enabled:e.target.checked}:ef))} className="w-3 h-3 accent-purple-600" />
                <input value={eff.name} onChange={e=>setEffects(p=>p.map((ef,j)=>j===i?{...ef,name:e.target.value}:ef))}
                  className="flex-1 bg-gray-900 text-white rounded px-1.5 py-0.5 text-[10px] border border-gray-700" />
                <button onClick={()=>setEffects(p=>p.filter((_,j)=>j!==i))} className="text-gray-600 hover:text-red-400 text-[10px]">✕</button>
              </div>
              {Object.entries(eff.params).map(([k,v])=>(
                <Sl key={k} label={k} value={v as number} min={0} max={1} step={0.01} fmt={val=>`${Math.round(val*100)}%`}
                  onChange={nv=>setEffects(p=>p.map((ef,j)=>j===i?{...ef,params:{...ef.params,[k]:nv}}:ef))} />
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* ── 템플릿 ── */}
      <div className="bg-gray-900 border border-indigo-900/50 rounded-xl p-3 mt-4">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-2">채널 템플릿</h3>
        <div className="flex gap-1.5 mb-2">
          <input value={tplName} onChange={e=>setTplName(e.target.value)} placeholder="템플릿 이름"
            className="flex-1 bg-gray-800 text-white rounded px-2 py-1.5 text-xs border border-gray-700 focus:outline-none focus:border-indigo-500" />
          <button disabled={!tplName.trim()||!project.channel_id} onClick={async()=>{
            if(!project.channel_id)return
            await api.channels.saveTemplate(project.channel_id,{name:tplName.trim(),waveform_layer:wf,text_layers:texts.map(({id:_,...r})=>r),effect_layers:effects})
            setTemplates(await api.channels.listTemplates(project.channel_id)); setTplName('')
          }} className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white px-3 py-1.5 rounded text-xs font-semibold">💾</button>
        </div>
        {templates.map(tpl=>(
          <div key={tpl.name} className="flex items-center gap-2 bg-gray-800 rounded-lg px-3 py-1.5 mb-1">
            <span className="flex-1 text-xs text-white">{tpl.name}</span>
            <button onClick={()=>{
              if(tpl.waveform_layer)setWf(mg(tpl.waveform_layer))
              if(tpl.text_layers)setTexts(tpl.text_layers.map(t=>({...t,id:crypto.randomUUID(),font_family:t.font_family||FONTS[0].value})))
              if(tpl.effect_layers)setEffects(tpl.effect_layers)
            }} className="text-[10px] text-indigo-400 hover:text-indigo-300 px-2 py-0.5 rounded border border-indigo-800">적용</button>
            <button onClick={async()=>{
              if(!project.channel_id)return
              await api.channels.deleteTemplate(project.channel_id,tpl.name)
              setTemplates(p=>p.filter(t=>t.name!==tpl.name))
            }} className="text-gray-600 hover:text-red-400 text-[10px]">✕</button>
          </div>
        ))}
      </div>
    </div>
  )
}
