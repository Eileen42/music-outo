import { useState, type FormEvent } from 'react'
import type { Project } from '../types'

interface Props {
  projects: Project[]
  onSelect: (p: Project) => void
  onCreate: (name: string, playlistTitle: string) => void
  onDelete: (id: string) => void
  activeProject?: Project
  onRefresh?: () => void
}

const STATUS_KO: Record<string, { label: string; color: string }> = {
  setup:      { label: '초기 설정', color: 'bg-gray-600 text-gray-200' },
  ready:      { label: '준비 완료', color: 'bg-green-700 text-green-100' },
  processing: { label: '처리 중',   color: 'bg-yellow-700 text-yellow-100' },
  uploading:  { label: '업로드 중', color: 'bg-blue-700 text-blue-100' },
  uploaded:   { label: '업로드 완료', color: 'bg-purple-700 text-purple-100' },
  error:      { label: '오류',      color: 'bg-red-700 text-red-100' },
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('ko-KR', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

export default function ProjectSetup({ projects, onSelect, onCreate, onDelete }: Props) {
  const [name, setName] = useState('')
  const [playlistTitle, setPlaylistTitle] = useState('')
  const [loading, setLoading] = useState(false)

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    setLoading(true)
    try {
      await onCreate(name.trim(), playlistTitle.trim())
      setName('')
      setPlaylistTitle('')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto p-6">
      {/* 타이틀 */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-white mb-1">🎬 YouTube 플레이리스트 자동화</h1>
        <p className="text-sm text-gray-500">
          음악 파일을 업로드하면 AI가 제목·설명·태그를 생성하고 영상을 자동으로 만들어 YouTube에 업로드합니다.
        </p>
      </div>

      {/* 새 프로젝트 생성 */}
      <div className="bg-gray-900 rounded-2xl p-5 mb-8 border border-gray-800">
        <h2 className="text-sm font-semibold text-gray-300 mb-1">새 프로젝트 만들기</h2>
        <p className="text-xs text-gray-600 mb-4">플레이리스트 하나 = 프로젝트 하나</p>
        <form onSubmit={handleCreate} className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-500 mb-1">프로젝트 이름 <span className="text-red-500">*</span></label>
              <input
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="예: 로파이 플레이리스트 vol.1"
                className="w-full bg-gray-800 text-white rounded-xl px-3 py-2.5 text-sm border border-gray-700 focus:outline-none focus:border-purple-500 placeholder-gray-600"
                required
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">YouTube 플레이리스트 제목</label>
              <input
                value={playlistTitle}
                onChange={e => setPlaylistTitle(e.target.value)}
                placeholder="예: Lo-Fi Hip Hop Study Music 🎧"
                className="w-full bg-gray-800 text-white rounded-xl px-3 py-2.5 text-sm border border-gray-700 focus:outline-none focus:border-purple-500 placeholder-gray-600"
              />
            </div>
          </div>
          <div>
            <button
              type="submit"
              disabled={loading || !name.trim()}
              className="bg-purple-600 hover:bg-purple-500 disabled:opacity-40 disabled:cursor-not-allowed text-white px-5 py-2.5 rounded-xl text-sm font-semibold transition-colors"
            >
              {loading ? '생성 중...' : '+ 프로젝트 생성'}
            </button>
          </div>
        </form>
      </div>

      {/* 프로젝트 목록 */}
      <div>
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-3">
          내 프로젝트 ({projects.length})
        </h2>

        {projects.length === 0 ? (
          <div className="text-center py-16 text-gray-700">
            <div className="text-4xl mb-3">📂</div>
            <div className="text-sm">아직 프로젝트가 없습니다.</div>
            <div className="text-xs mt-1">위에서 첫 번째 프로젝트를 만들어보세요!</div>
          </div>
        ) : (
          <div className="space-y-2">
            {projects.map(p => {
              const si = STATUS_KO[p.status] || { label: p.status, color: 'bg-gray-700 text-gray-200' }
              const tracksDone = p.tracks.length > 0
              const imageDone = !!(p.images?.thumbnail || p.images?.background)
              const metaDone = !!p.metadata?.title
              const buildDone = p.build?.status === 'done'
              const ytDone = !!p.youtube?.video_id

              return (
                <div
                  key={p.id}
                  className="bg-gray-900 border border-gray-800 rounded-2xl p-4 hover:border-gray-700 transition-colors group"
                >
                  <div className="flex items-center gap-3">
                    {/* 클릭 영역 */}
                    <div className="flex-1 min-w-0 cursor-pointer" onClick={() => onSelect(p)}>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-semibold text-white truncate">{p.name}</span>
                        <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium shrink-0 ${si.color}`}>
                          {si.label}
                        </span>
                      </div>
                      {p.playlist_title && (
                        <div className="text-xs text-gray-500 truncate mb-2">{p.playlist_title}</div>
                      )}
                      {/* 진행 체크 뱃지 */}
                      <div className="flex gap-1.5 flex-wrap">
                        {[
                          { ok: tracksDone, label: `트랙 ${p.tracks.length}개` },
                          { ok: imageDone,  label: '이미지' },
                          { ok: metaDone,   label: '메타데이터' },
                          { ok: buildDone,  label: '빌드' },
                          { ok: ytDone,     label: 'YouTube' },
                        ].map(item => (
                          <span
                            key={item.label}
                            className={`text-[11px] px-2 py-0.5 rounded-full ${
                              item.ok
                                ? 'bg-green-900/50 text-green-400 border border-green-800'
                                : 'bg-gray-800 text-gray-600 border border-gray-700'
                            }`}
                          >
                            {item.ok ? '✓ ' : ''}{item.label}
                          </span>
                        ))}
                      </div>
                    </div>

                    {/* 날짜 + 버튼 */}
                    <div className="shrink-0 flex flex-col items-end gap-2">
                      <span className="text-xs text-gray-600">{formatDate(p.updated_at)}</span>
                      <div className="flex gap-1.5">
                        <button
                          onClick={() => onSelect(p)}
                          className="text-xs bg-purple-700 hover:bg-purple-600 text-white px-3 py-1.5 rounded-lg transition-colors font-medium"
                        >
                          열기 →
                        </button>
                        <button
                          onClick={() => { if (confirm(`"${p.name}" 프로젝트를 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.`)) onDelete(p.id) }}
                          className="text-xs text-gray-600 hover:text-red-400 px-2 py-1.5 transition-colors"
                        >
                          삭제
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
