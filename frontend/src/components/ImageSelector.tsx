import { useEffect, useRef, useState, type DragEvent } from 'react'
import type { Project, ImageMood } from '../types'
import { api } from '../api/client'

// 링크 아이템 컴포넌트 (Hook 규칙 준수)
function LinkItem({ link, isFolder, projectId, onSave, onDelete }: {
  link: { name: string; url: string; category: string }
  isFolder: boolean; projectId: string
  onSave: (name: string, url: string) => void; onDelete: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [eName, setEName] = useState(link.name)
  const [eUrl, setEUrl] = useState(link.url)

  if (editing) {
    return (
      <div className="flex items-center gap-1.5">
        <input value={eName} onChange={e => setEName(e.target.value)}
          className="w-24 bg-gray-800 text-white rounded px-2 py-1 text-xs border border-gray-700" />
        <input value={eUrl} onChange={e => setEUrl(e.target.value)}
          className="flex-1 bg-gray-800 text-white rounded px-2 py-1 text-xs border border-gray-700" />
        <button onClick={() => { onSave(eName, eUrl); setEditing(false) }} className="text-xs text-green-400 px-1">✓</button>
        <button onClick={() => setEditing(false)} className="text-xs text-gray-600 px-1">✕</button>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-1.5">
      {isFolder ? (
        <button onClick={() => {
          fetch(`${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/projects/${projectId}/build/open-folder`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: link.url })
          }).catch(() => {})
        }} className="flex-1 bg-amber-900/30 border border-amber-800 rounded-lg px-3 py-2 hover:bg-amber-900/50 transition-colors text-left flex items-center gap-2">
          <span>📂</span><span className="text-xs text-amber-300 font-semibold truncate">{link.name}</span>
        </button>
      ) : (
        <a href={link.url} target="_blank" rel="noopener noreferrer"
          className="flex-1 bg-indigo-900/30 border border-indigo-800 rounded-lg px-3 py-2 hover:bg-indigo-900/50 transition-colors flex items-center gap-2">
          <span>🎨</span><span className="text-xs text-indigo-300 font-semibold truncate">{link.name}</span>
          <span className="text-gray-600 text-[10px] ml-auto">↗</span>
        </a>
      )}
      <button onClick={() => setEditing(true)} className="text-gray-700 hover:text-gray-400 text-[10px]">✏️</button>
      <button onClick={onDelete} className="text-gray-700 hover:text-red-400 text-[10px]">✕</button>
    </div>
  )
}

interface Props {
  project: Project
  onRefresh: () => void
}

type Tab = 'upload' | 'analyze' | 'generated'

const MOOD_LABELS: Record<string, string> = {
  mood: '전체 분위기',
  atmosphere: '공간감',
  style: '스타일',
  lighting: '조명',
  time_of_day: '시간대',
  season: '계절',
  emotion: '감정',
  music_genre_fit: '어울리는 장르',
}

export default function ImageSelector({ project, onRefresh }: Props) {
  const [tab, setTab] = useState<Tab>('upload')

  // 업로드 탭 상태
  const [uploadCat, setUploadCat] = useState<'thumbnail' | 'background' | 'additional'>('background')
  const [uploading, setUploading] = useState(false)
  const [draggingUpload, setDraggingUpload] = useState(false)
  const [editToolLinks, setEditToolLinks] = useState<{name: string; url: string; category: string}[]>([])
  const [newToolName, setNewToolName] = useState('')
  const [newToolUrl, setNewToolUrl] = useState('')
  const [showingAdd, setShowingAdd] = useState(false)
  const [generatedPrompt, setGeneratedPrompt] = useState('')

  // 채널에 저장된 편집툴 링크 로드
  useEffect(() => {
    if (project.channel_id) {
      api.channels.get(project.channel_id).then(ch => {
        setEditToolLinks((ch as unknown as {image_tool_links?: {name:string;url:string;category:string}[]}).image_tool_links || [])
      }).catch(() => {})
    }
  }, [project.channel_id])

  const saveLinks = async (updated: typeof editToolLinks) => {
    setEditToolLinks(updated)
    if (project.channel_id) await api.channels.update(project.channel_id, { image_tool_links: updated } as Partial<import('../types').Channel>)
  }
  const uploadRef = useRef<HTMLInputElement>(null)

  // 분석 탭 상태
  const [refFile, setRefFile] = useState<File | null>(null)
  const [refPreview, setRefPreview] = useState<string | null>(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [mood, setMood] = useState<ImageMood | null>(project.image_mood ?? null)
  const [draggingRef, setDraggingRef] = useState(false)
  const refInputRef = useRef<HTMLInputElement>(null)

  // 생성 탭 상태
  const [genTarget, setGenTarget] = useState<'background' | 'thumbnail' | 'both'>('background')
  const [genCount, setGenCount] = useState(1)
  const [generating, setGenerating] = useState(false)
  const [genResults, setGenResults] = useState<{ b64: string; path: string; target: string; prompt: string; error?: string }[]>([])
  const [saveMsg, setSaveMsg] = useState('')
  const [customPrompt, setCustomPrompt] = useState('')

  const images = project.images || { thumbnail: null, background: null, additional: [] }

  // ─── 업로드 탭 ───────────────────────────────────────────

  const handleUploadFile = async (file: File, category = uploadCat) => {
    setUploading(true)
    try {
      await api.images.upload(project.id, file, category)
      await onRefresh()
    } catch (e: unknown) {
      alert('업로드 실패: ' + (e as { message?: string })?.message)
    } finally {
      setUploading(false)
    }
  }

  const handleUploadDrop = async (e: DragEvent) => {
    e.preventDefault(); setDraggingUpload(false)
    const file = e.dataTransfer.files?.[0]
    if (file) await handleUploadFile(file)
  }

  const handleRemove = async (path: string, category: 'thumbnail' | 'background' | 'additional') => {
    await api.images.remove(project.id, path, category)
    await onRefresh()
  }

  // ─── 분석 탭 ───────────────────────────────────────────

  const pickRefFile = (file: File) => {
    setRefFile(file)
    const url = URL.createObjectURL(file)
    setRefPreview(url)
    setMood(null)
  }

  const handleRefDrop = (e: DragEvent) => {
    e.preventDefault(); setDraggingRef(false)
    const file = e.dataTransfer.files?.[0]
    if (file) pickRefFile(file)
  }

  const handleAnalyze = async () => {
    if (!refFile) return
    setAnalyzing(true)
    try {
      const result = await api.images.analyzeMood(project.id, refFile)
      setMood(result)
      await onRefresh()
      setTab('analyze')
    } catch (e: unknown) {
      alert('분석 실패: ' + (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || String(e))
    } finally {
      setAnalyzing(false)
    }
  }

  // ─── 생성 탭 ───────────────────────────────────────────

  const handleGenerate = async () => {
    const useMood = mood ?? project.image_mood
    if (!customPrompt.trim() && !useMood) {
      alert('이미지 설명을 입력하거나, 먼저 레퍼런스 이미지를 분석하세요.')
      return
    }
    setGenerating(true)
    setGenResults([])
    setSaveMsg('')
    try {
      const res = await api.images.generate(project.id, useMood ?? null, genTarget, genCount, undefined, customPrompt.trim() || undefined)
      const items = (res.generated || []).map((g: { image_b64?: string; stored_path?: string; target?: string; prompt?: string; error?: string }) => ({
        b64: g.image_b64 || '',
        path: g.stored_path || '',
        target: g.target || '',
        prompt: g.prompt || '',
        error: g.error,
      }))
      setGenResults(items)
      await onRefresh()
    } catch (e: unknown) {
      alert('생성 실패: ' + (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || String(e))
    } finally {
      setGenerating(false)
    }
  }

  const handleUseImage = async (item: typeof genResults[0], category: 'thumbnail' | 'background') => {
    if (!item.path) return
    await api.images.assign(project.id, item.path, category)
    await onRefresh()
    setSaveMsg(`✅ ${category === 'thumbnail' ? '썸네일' : '배경'}으로 저장됨`)
  }

  const activeMood = mood ?? project.image_mood

  // ─── UI ───────────────────────────────────────────

  return (
    <div>
      {/* 탭 */}
      <div className="flex gap-1 mb-6 bg-gray-900 border border-gray-800 rounded-2xl p-1">
        {([
          { id: 'upload',    icon: '📁', label: '직접 업로드' },
          { id: 'analyze',   icon: '🔍', label: 'AI 분위기 분석' },
          { id: 'generated', icon: '✨', label: 'AI 이미지 생성' },
        ] as const).map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-medium transition-colors ${
              tab === t.id ? 'bg-purple-700 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800'
            }`}
          >
            {t.icon} {t.label}
            {t.id === 'analyze' && activeMood && (
              <span className="w-2 h-2 bg-green-400 rounded-full" />
            )}
          </button>
        ))}
      </div>

      {/* ══ 탭 1: 직접 업로드 ══ */}
      {tab === 'upload' && (
        <div className="space-y-5">
          {/* 카테고리 선택 */}
          <div className="flex gap-2">
            {([
              { id: 'background', label: '🖼 배경 (1920×1080)', desc: '영상 배경 이미지' },
              { id: 'thumbnail',  label: '🎯 썸네일 (1280×720)', desc: 'YouTube 썸네일 · 미리캔버스' },
              { id: 'additional', label: '📂 참고용', desc: '분위기 참고 이미지' },
            ] as const).map(c => (
              <button
                key={c.id}
                onClick={() => setUploadCat(c.id)}
                className={`flex-1 py-2.5 rounded-xl text-xs font-medium border transition-colors ${
                  uploadCat === c.id
                    ? 'bg-purple-700 border-purple-500 text-white'
                    : 'bg-gray-900 border-gray-700 text-gray-400 hover:bg-gray-800'
                }`}
              >
                <div>{c.label}</div>
                <div className={`mt-0.5 ${uploadCat === c.id ? 'text-purple-200' : 'text-gray-600'}`}>{c.desc}</div>
              </button>
            ))}
          </div>

          {/* 바로가기 — 선택한 카테고리 전용 */}
          {(() => {
            const catLinks = editToolLinks.filter(l => l.category === uploadCat)
            const isFolder = uploadCat === 'additional'
            const catTitle = uploadCat === 'background' ? '배경 만들러 바로가기' : uploadCat === 'thumbnail' ? '썸네일 만들러 바로가기' : '참고용 이미지 보러가기'
            const [showAdd, setShowAdd] = [showingAdd, setShowingAdd]
            return (
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-3 space-y-2">
                <div className="text-[10px] text-gray-500 uppercase tracking-widest">{catTitle}</div>
                {catLinks.length === 0 && !showAdd && (
                  <p className="text-[10px] text-gray-700">등록된 링크가 없습니다.</p>
                )}
                {catLinks.map((link) => {
                  const realIdx = editToolLinks.indexOf(link)
                  return (
                    <LinkItem key={realIdx} link={link} isFolder={isFolder} projectId={project.id}
                      onSave={(name, url) => {
                        const updated = [...editToolLinks]; updated[realIdx] = { ...link, name, url }
                        saveLinks(updated)
                      }}
                      onDelete={() => saveLinks(editToolLinks.filter((_, j) => j !== realIdx))}
                    />
                  )
                })}
                {showAdd ? (
                  <div className="flex gap-1.5 pt-1 border-t border-gray-800">
                    <input value={newToolName} onChange={e => setNewToolName(e.target.value)}
                      placeholder={isFolder ? '폴더 이름' : '편집툴 이름'}
                      className="w-24 bg-gray-800 text-white rounded-lg px-2 py-1.5 text-[10px] border border-gray-700" autoFocus />
                    <input value={newToolUrl} onChange={e => setNewToolUrl(e.target.value)}
                      placeholder={isFolder ? 'D:\\폴더\\경로' : 'https://...'}
                      className="flex-1 bg-gray-800 text-white rounded-lg px-2 py-1.5 text-[10px] border border-gray-700" />
                    <button onClick={() => {
                      if (!newToolName.trim() || !newToolUrl.trim()) return
                      saveLinks([...editToolLinks, { name: newToolName.trim(), url: newToolUrl.trim(), category: uploadCat }])
                      setNewToolName(''); setNewToolUrl(''); setShowAdd(false)
                    }} disabled={!newToolName.trim() || !newToolUrl.trim()}
                      className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white px-2 py-1.5 rounded-lg text-[10px] font-semibold">저장</button>
                    <button onClick={() => setShowAdd(false)}
                      className="text-gray-600 hover:text-gray-400 text-[10px] px-1">취소</button>
                  </div>
                ) : (
                  <button onClick={() => setShowAdd(true)}
                    className="text-[10px] text-indigo-400 hover:text-indigo-300 pt-1">+ 추가</button>
                )}
              </div>
            )
          })()}

          {/* 드래그앤드롭 + 붙여넣기 */}
          <div
            tabIndex={0}
            onDragOver={e => { e.preventDefault(); setDraggingUpload(true) }}
            onDragLeave={() => setDraggingUpload(false)}
            onDrop={handleUploadDrop}
            onPaste={async (e) => {
              const items = e.clipboardData?.items
              if (!items) return
              for (const item of Array.from(items)) {
                if (item.type.startsWith('image/')) {
                  const file = item.getAsFile()
                  if (file) {
                    const ext = file.type.split('/')[1] || 'png'
                    const named = new File([file], `paste_${Date.now()}.${ext}`, { type: file.type })
                    await handleUploadFile(named)
                  }
                  break
                }
              }
            }}
            onClick={() => uploadRef.current?.click()}
            className={`flex flex-col items-center justify-center gap-2 border-2 border-dashed rounded-2xl py-10 cursor-pointer transition-all focus:border-purple-500 focus:outline-none ${
              draggingUpload ? 'border-purple-500 bg-purple-900/20' : 'border-gray-700 bg-gray-900/50 hover:border-gray-600'
            }`}
          >
            <span className="text-3xl">{uploading ? '⏳' : '🖼️'}</span>
            <p className="text-sm text-gray-300 font-medium">
              {uploading ? '업로드 중...' : '이미지를 드래그, 클릭 또는 Ctrl+V로 붙여넣기'}
            </p>
            <p className="text-xs text-gray-600">JPG, PNG, WEBP 지원 · 캡처 이미지 붙여넣기 가능</p>
            <input
              ref={uploadRef}
              type="file"
              accept=".jpg,.jpeg,.png,.webp"
              className="hidden"
              onChange={e => { const f = e.target.files?.[0]; if (f) handleUploadFile(f) }}
            />
          </div>

          {/* 현재 이미지 미리보기 */}
          <div className="grid grid-cols-2 gap-4">
            {(['background', 'thumbnail'] as const).map(cat => {
              const path = images[cat]
              const label = cat === 'background' ? '배경 이미지' : '썸네일'
              return (
                <div key={cat} className="bg-gray-900 border border-gray-800 rounded-2xl p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-gray-400">{label}</span>
                    {path && (
                      <button
                        onClick={() => handleRemove(path, cat)}
                        className="text-xs text-gray-600 hover:text-red-400"
                      >삭제</button>
                    )}
                  </div>
                  {path ? (
                    <img
                      src={api.images.storageUrl(path)}
                      alt={cat}
                      className="w-full h-28 object-cover rounded-xl"
                      onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                    />
                  ) : (
                    <div
                      onClick={() => { setUploadCat(cat); uploadRef.current?.click() }}
                      className="h-28 bg-gray-800 rounded-xl flex items-center justify-center text-gray-600 text-sm cursor-pointer hover:bg-gray-750 transition-colors"
                    >
                      + 추가
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {images.additional.length > 0 && (
            <div className="bg-gray-900 border border-gray-800 rounded-2xl p-4">
              <h3 className="text-xs font-semibold text-gray-400 mb-3">참고 이미지</h3>
              <div className="grid grid-cols-4 gap-2">
                {images.additional.map((path, i) => (
                  <div key={i} className="relative group">
                    <img
                      src={api.images.storageUrl(path)}
                      className="w-full h-16 object-cover rounded-lg"
                    />
                    <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 flex items-center justify-center gap-1 rounded-lg transition-opacity">
                      <button onClick={() => api.images.assign(project.id, path, 'thumbnail').then(onRefresh)} className="text-[10px] bg-purple-600 text-white px-1.5 py-0.5 rounded">썸네일</button>
                      <button onClick={() => api.images.assign(project.id, path, 'background').then(onRefresh)} className="text-[10px] bg-blue-600 text-white px-1.5 py-0.5 rounded">배경</button>
                      <button onClick={() => handleRemove(path, 'additional')} className="text-[10px] bg-red-600 text-white px-1.5 py-0.5 rounded">✕</button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ══ 탭 2: AI 분위기 분석 ══ */}
      {tab === 'analyze' && (
        <div className="space-y-5">
          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
            <h3 className="text-sm font-semibold text-gray-200 mb-1">레퍼런스 이미지 업로드</h3>
            <p className="text-xs text-gray-500 mb-4">
              원하는 분위기의 이미지를 올리면 Gemini가 색감·조명·감정·스타일을 정밀 분석합니다.
              분석 결과로 동일한 분위기의 새 이미지를 생성할 수 있습니다.
            </p>

            <div
              onDragOver={e => { e.preventDefault(); setDraggingRef(true) }}
              onDragLeave={() => setDraggingRef(false)}
              onDrop={handleRefDrop}
              onClick={() => refInputRef.current?.click()}
              className={`flex items-center gap-4 border-2 border-dashed rounded-2xl p-4 cursor-pointer transition-all ${
                draggingRef ? 'border-purple-500 bg-purple-900/20' : 'border-gray-700 hover:border-gray-600 bg-gray-800/50'
              }`}
            >
              {refPreview ? (
                <>
                  <img src={refPreview} className="w-24 h-16 object-cover rounded-xl shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-gray-200 truncate">{refFile?.name}</p>
                    <p className="text-xs text-gray-500 mt-0.5">다른 이미지로 교체하려면 클릭</p>
                  </div>
                </>
              ) : (
                <div className="flex flex-col items-center justify-center w-full py-4 gap-2">
                  <span className="text-3xl">🎨</span>
                  <p className="text-sm text-gray-400">레퍼런스 이미지를 드래그하거나 클릭</p>
                </div>
              )}
              <input
                ref={refInputRef}
                type="file"
                accept=".jpg,.jpeg,.png,.webp"
                className="hidden"
                onChange={e => { const f = e.target.files?.[0]; if (f) pickRefFile(f) }}
              />
            </div>

            <button
              onClick={handleAnalyze}
              disabled={!refFile || analyzing}
              className="mt-4 w-full bg-purple-600 hover:bg-purple-500 disabled:opacity-40 disabled:cursor-not-allowed text-white py-3 rounded-xl font-semibold text-sm transition-colors"
            >
              {analyzing ? '🔍 Gemini가 분위기를 분석하는 중...' : '🔍 분위기 분석 시작'}
            </button>
          </div>

          {/* 분석 결과 */}
          {activeMood && (
            <div className="bg-gray-900 border border-purple-800/50 rounded-2xl p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-semibold text-purple-300">분위기 분석 결과</h3>
                <button
                  onClick={() => setTab('generated')}
                  className="text-xs bg-purple-600 hover:bg-purple-500 text-white px-3 py-1.5 rounded-lg"
                >
                  이걸로 이미지 생성 →
                </button>
              </div>

              {/* 색상 팔레트 */}
              {activeMood.colors?.dominant?.length > 0 && (
                <div className="flex items-center gap-2 mb-4">
                  <span className="text-xs text-gray-500 w-16 shrink-0">색상</span>
                  <div className="flex gap-1.5">
                    {activeMood.colors.dominant.map((hex, i) => (
                      <div
                        key={i}
                        className="w-8 h-8 rounded-lg border border-gray-700 shrink-0"
                        style={{ backgroundColor: hex }}
                        title={hex}
                      />
                    ))}
                  </div>
                  <span className="text-xs text-gray-500">{activeMood.colors.tone}</span>
                </div>
              )}

              {/* 분위기 키워드들 */}
              <div className="space-y-2 mb-4">
                {Object.entries(MOOD_LABELS).map(([key, label]) => {
                  const val = activeMood[key as keyof ImageMood]
                  if (!val || typeof val !== 'string') return null
                  return (
                    <div key={key} className="flex gap-3 text-sm">
                      <span className="text-gray-600 w-24 shrink-0 text-xs pt-0.5">{label}</span>
                      <span className="text-gray-300 flex-1 leading-snug">{val}</span>
                    </div>
                  )
                })}
                {activeMood.elements?.length > 0 && (
                  <div className="flex gap-3 text-sm">
                    <span className="text-gray-600 w-24 shrink-0 text-xs pt-0.5">주요 요소</span>
                    <div className="flex gap-1.5 flex-wrap">
                      {activeMood.elements.map((el, i) => (
                        <span key={i} className="text-xs bg-gray-800 text-gray-300 px-2 py-0.5 rounded-full border border-gray-700">{el}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* 생성 프롬프트 미리보기 */}
              <div className="bg-gray-800 rounded-xl p-3">
                <p className="text-xs text-gray-500 mb-1">배경 생성 프롬프트</p>
                <p className="text-xs text-gray-400 leading-relaxed font-mono">{activeMood.background_prompt}</p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ══ 탭 3: AI 이미지 생성 ══ */}
      {tab === 'generated' && (
        <div className="space-y-5">
          {/* 분석된 분위기 요약 (있을 때만) */}
          {activeMood && (
            <div className="bg-gray-900 border border-purple-800/40 rounded-2xl p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-purple-400 font-semibold">분석된 분위기</span>
                <button onClick={() => setTab('analyze')} className="text-xs text-gray-600 hover:text-gray-400">수정 →</button>
              </div>
              <p className="text-sm text-gray-300 mb-2">{activeMood.mood}</p>
              <div className="flex gap-1.5 flex-wrap">
                {activeMood.colors?.dominant?.map((hex, i) => (
                  <div key={i} className="w-5 h-5 rounded" style={{ backgroundColor: hex }} title={hex} />
                ))}
                {[activeMood.time_of_day, activeMood.season, activeMood.style].filter(Boolean).map((tag, i) => (
                  <span key={i} className="text-[11px] bg-gray-800 text-gray-400 px-2 py-0.5 rounded-full">{tag}</span>
                ))}
              </div>
            </div>
          )}

              {/* 생성 설정 */}
              <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
                <h3 className="text-sm font-semibold text-gray-200 mb-4">생성 설정</h3>

                {/* 직접 입력 프롬프트 */}
                <div className="mb-4">
                  <label className="text-xs text-gray-500 block mb-1.5">
                    원하는 이미지 설명
                    <span className="text-gray-600 ml-1">(입력 시 분위기 분석 결과 대신 사용됩니다)</span>
                  </label>
                  <textarea
                    value={customPrompt}
                    onChange={e => setCustomPrompt(e.target.value)}
                    placeholder={activeMood
                      ? `비워두면 분석된 분위기(${activeMood.mood})로 생성됩니다.\n예: A serene mountain lake at sunset with golden reflections`
                      : '예: A serene mountain lake at sunset with golden reflections\n한국어도 가능: 저녁 노을이 지는 조용한 호수'}
                    rows={3}
                    className="w-full bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-sm text-gray-200 placeholder-gray-600 resize-none focus:outline-none focus:border-purple-500 transition-colors"
                  />
                </div>


                {/* 생성된 프롬프트 (📝 프롬프트 생성 후 표시) */}
                {generatedPrompt && (
                  <div className="bg-gray-800 rounded-xl p-3 mb-4">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] text-green-400">✓ 프롬프트 생성 완료 · 클립보드 복사됨</span>
                      <button onClick={() => navigator.clipboard.writeText(generatedPrompt)}
                        className="text-[10px] text-indigo-400 hover:text-indigo-300">복사</button>
                    </div>
                    <p className="text-[11px] text-gray-400 leading-relaxed max-h-24 overflow-y-auto">{generatedPrompt}</p>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-2">
                  <button
                    onClick={handleGenerate}
                    disabled={generating}
                    className="bg-purple-600 hover:bg-purple-500 disabled:opacity-40 text-white py-3 rounded-xl font-bold text-sm transition-colors"
                  >
                    {generating ? '⏳ 생성 중...' : '✨ 이미지 생성'}
                  </button>
                  <button
                    onClick={() => {
                      const m = activeMood
                      const desc = customPrompt.trim()
                      const parts: string[] = []
                      if (m) {
                        parts.push(`${m.mood}, ${m.atmosphere}.`)
                        if (m.colors?.dominant?.length) parts.push(`Colors: ${m.colors.dominant.join(', ')}, ${m.colors?.tone || ''} tone.`)
                        parts.push(`${m.style}, ${m.lighting} lighting, ${m.time_of_day}, ${m.season}.`)
                      }
                      if (desc) parts.push(desc + '.')
                      parts.push(`Soft focus, gentle grain, natural photograph, no people, no text, no watermark, 16:9.`)
                      const prompt = parts.join(' ')
                      // customPrompt는 건드리지 않음 — 별도 generatedPrompt로 표시
                      setGeneratedPrompt(prompt)
                      navigator.clipboard.writeText(prompt)
                    }}
                    className="bg-indigo-600 hover:bg-indigo-500 text-white py-3 rounded-xl font-bold text-sm transition-colors"
                  >
                    📝 프롬프트 생성
                  </button>
                </div>
                <div className="flex items-center justify-center gap-2 mt-2">
                  <a href="https://labs.google/fx/tools/image-fx" target="_blank" rel="noopener noreferrer"
                    className="text-[10px] text-indigo-400 hover:text-indigo-300 flex items-center gap-1">
                    🌐 Flow에서 만들기 ↗
                  </a>
                  <span className="text-[10px] text-gray-700">·</span>
                  <span className="text-[10px] text-gray-600">프롬프트 생성 → 복사됨 → Flow에 붙여넣기</span>
                </div>

                {generating && (
                  <p className="text-xs text-gray-500 text-center mt-2">
                    이미지 생성 중... 10~30초 소요
                  </p>
                )}
              </div>

              {/* 생성 결과 */}
              {genResults.length > 0 && (
                <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-sm font-semibold text-gray-200">생성된 이미지</h3>
                    {saveMsg && <span className="text-xs text-green-400">{saveMsg}</span>}
                  </div>
                  <div className="space-y-4">
                    {genResults.map((item, i) => (
                      <div key={i} className={`rounded-2xl overflow-hidden border ${item.error ? 'border-red-800 bg-red-950/20' : 'border-gray-700'}`}>
                        {item.error ? (
                          <div className="p-4 text-red-400 text-sm">❌ {item.error}</div>
                        ) : (
                          <>
                            <img
                              src={`data:image/png;base64,${item.b64}`}
                              alt={`생성 ${i + 1}`}
                              className="w-full object-cover max-h-72"
                            />
                            <div className="p-3 bg-gray-900">
                              <p className="text-xs text-gray-600 mb-2 font-mono leading-relaxed line-clamp-2">{item.prompt}</p>
                              <div className="flex gap-2">
                                <button
                                  onClick={() => handleUseImage(item, 'background')}
                                  className="text-xs bg-blue-700 hover:bg-blue-600 text-white px-3 py-1.5 rounded-lg transition-colors"
                                >
                                  배경으로 사용
                                </button>
                                <button
                                  onClick={() => handleUseImage(item, 'thumbnail')}
                                  className="text-xs bg-purple-700 hover:bg-purple-600 text-white px-3 py-1.5 rounded-lg transition-colors"
                                >
                                  썸네일로 사용
                                </button>
                                <span className="text-xs text-gray-600 self-center ml-auto">
                                  {item.target === 'background' ? '배경용' : '썸네일용'}
                                </span>
                              </div>
                            </div>
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
        </div>
      )}
    </div>
  )
}
