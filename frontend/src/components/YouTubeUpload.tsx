import { useEffect, useState } from 'react'
import type { Project } from '../types'
import { api } from '../api/client'

interface Props {
  project: Project
  onRefresh: () => void
}

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function YouTubeUpload({ project, onRefresh }: Props) {
  const [authorized, setAuthorized] = useState(false)
  const [authUrl, setAuthUrl] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [privacyStatus, setPrivacyStatus] = useState('unlisted')
  const [loading, setLoading] = useState(true)
  const [showGuide, setShowGuide] = useState(false)

  const yt = project.youtube || { video_id: null, url: null, uploaded_at: null }
  const buildDone = project.build?.status === 'done'

  // 영상 파일 업로드 폴더 경로
  const uploadFolder = `D:\\coding\\music_outo\\backend\\storage\\projects\\${project.id}\\outputs`

  const channelId = project.channel_id || '_default'

  useEffect(() => {
    api.youtube.status(channelId).then((s) => {
      setAuthorized(s.authorized)
      setLoading(false)
    })
    const params = new URLSearchParams(window.location.search)
    if (params.get('youtube_auth') === 'success') {
      setAuthorized(true)
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [channelId])

  useEffect(() => {
    if (project.status !== 'uploading') return
    const interval = setInterval(async () => {
      try {
        const s = await api.youtube.uploadStatus(project.id)
        setUploadProgress(s.upload_progress || 0)
        if (s.status !== 'uploading') {
          setUploadProgress(100)
          await onRefresh()
          clearInterval(interval)
        }
      } catch {
        // 서버 일시 끊김 무시 — 다음 폴링에서 재시도
      }
    }, 5000)
    return () => clearInterval(interval)
  }, [project.status, project.id, onRefresh])

  const handleGetAuthUrl = async () => {
    const { auth_url } = await api.youtube.getAuthUrl()
    setAuthUrl(auth_url)
  }

  const handleRevoke = async () => {
    await api.youtube.revoke()
    setAuthorized(false)
    setAuthUrl(null)
  }

  const handleUpload = async () => {
    const privacyLabel = privacyStatus === 'private' ? '비공개' : privacyStatus === 'unlisted' ? '미등록' : '공개'
    if (!confirm(`YouTube에 [${privacyLabel}] 상태로 업로드하시겠습니까?`)) return
    setUploading(true)
    setUploadProgress(0)
    try {
      await api.youtube.upload(project.id, privacyStatus)
      await onRefresh()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } }; message?: string })
      alert('업로드 실패: ' + (msg?.response?.data?.detail || msg?.message || '알 수 없는 오류'))
    } finally {
      setUploading(false)
    }
  }

  if (loading) return (
    <div className="flex items-center gap-2 text-gray-500 text-sm py-8 justify-center">
      <span className="animate-spin">⏳</span> 로딩 중...
    </div>
  )

  return (
    <div>
      {/* 업로드 완료 */}
      {yt.video_id && (
        <div className="bg-green-950/40 border border-green-700 rounded-2xl p-4 mb-5">
          <div className="text-green-400 font-semibold text-sm mb-2">✅ YouTube 업로드 완료</div>
          <a href={yt.url || `https://www.youtube.com/watch?v=${yt.video_id}`} target="_blank" rel="noopener noreferrer"
            className="text-blue-400 hover:text-blue-300 hover:underline text-sm break-all">
            {yt.url || `https://www.youtube.com/watch?v=${yt.video_id}`}
          </a>
          {yt.uploaded_at && <div className="text-xs text-gray-600 mt-1.5">업로드: {new Date(yt.uploaded_at).toLocaleString('ko-KR')}</div>}
        </div>
      )}

      {/* ── STEP 1: Google 계정 연결 ── */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 mb-4">
        <div className="flex items-center gap-2 mb-1">
          <span className="w-5 h-5 rounded-full bg-gray-700 text-gray-400 text-xs flex items-center justify-center font-bold shrink-0">1</span>
          <h3 className="text-sm font-semibold text-gray-200">Google 계정 연결</h3>
          {authorized && <span className="text-green-400 text-xs ml-auto">✅ 연결됨</span>}
        </div>

        {authorized ? (
          <div className="ml-7 flex items-center gap-3">
            <span className="text-green-400 text-sm font-medium">✅ YouTube 채널 연결됨</span>
          </div>
        ) : (
          <div className="ml-7">
            <p className="text-xs text-yellow-400 mb-2">⚠ YouTube 채널이 연결되지 않았습니다.</p>
            <p className="text-xs text-gray-500">홈 화면의 <strong>채널 카드</strong>에서 "▶ YouTube 채널 연결"을 클릭하세요.</p>
          </div>
        )}
      </div>

      {/* ── STEP 2: 영상 파일 준비 ── */}
      {authorized && (
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 mb-4">
          <div className="flex items-center gap-2 mb-1">
            <span className="w-5 h-5 rounded-full bg-gray-700 text-gray-400 text-xs flex items-center justify-center font-bold shrink-0">2</span>
            <h3 className="text-sm font-semibold text-gray-200">영상 파일 준비</h3>
          </div>
          <div className="ml-7 space-y-3">
            <p className="text-xs text-gray-500">
              CapCut에서 편집 완료한 영상(MP4)을 아래 폴더에 넣어주세요.
              폴더에 MP4 파일이 있으면 업로드할 수 있습니다.
            </p>

            {/* 폴더 경로 */}
            <div className="bg-gray-800 rounded-xl p-3">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-gray-400">영상 파일 경로</span>
                <div className="flex gap-2">
                  <button onClick={() => api.build.openFolder(project.id)}
                    className="text-[10px] bg-indigo-700 hover:bg-indigo-600 text-white px-2 py-0.5 rounded">📂 폴더 열기</button>
                  <button onClick={() => navigator.clipboard.writeText(uploadFolder)}
                    className="text-[10px] text-indigo-400 hover:text-indigo-300">복사</button>
                </div>
              </div>
              <div className="text-xs text-gray-300 font-mono break-all select-all bg-gray-900 rounded-lg px-3 py-2">
                {uploadFolder}
              </div>
            </div>

            <div className="bg-gray-800/50 rounded-xl p-3 space-y-1.5">
              <p className="text-[10px] text-gray-500 font-semibold">워크플로우:</p>
              <div className="flex items-center gap-2 text-[10px] text-gray-400">
                <span className="bg-indigo-900/50 text-indigo-300 px-1.5 py-0.5 rounded">빌드</span>
                <span>→</span>
                <span className="bg-indigo-900/50 text-indigo-300 px-1.5 py-0.5 rounded">CapCut에서 편집</span>
                <span>→</span>
                <span className="bg-indigo-900/50 text-indigo-300 px-1.5 py-0.5 rounded">MP4 내보내기</span>
                <span>→</span>
                <span className="bg-green-900/50 text-green-300 px-1.5 py-0.5 rounded">위 폴더에 넣기</span>
                <span>→</span>
                <span className="bg-red-900/50 text-red-300 px-1.5 py-0.5 rounded">업로드</span>
              </div>
              <p className="text-[10px] text-gray-600">파일명: <code className="bg-gray-900 px-1 rounded">output.mp4</code> 또는 아무 이름의 .mp4 파일</p>
            </div>

            {/* 현재 폴더 상태 */}
            {buildDone ? (
              <div className="text-xs text-green-400">✓ outputs 폴더 준비됨 — MP4 파일을 넣어주세요</div>
            ) : (
              <div className="text-xs text-yellow-500">⚠ 먼저 빌드 단계에서 CapCut 프로젝트를 빌드하세요</div>
            )}
          </div>
        </div>
      )}

      {/* ── STEP 3: 업로드 설정 ── */}
      {authorized && (
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
          <div className="flex items-center gap-2 mb-1">
            <span className="w-5 h-5 rounded-full bg-gray-700 text-gray-400 text-xs flex items-center justify-center font-bold shrink-0">3</span>
            <h3 className="text-sm font-semibold text-gray-200">업로드 설정</h3>
          </div>
          <div className="ml-7 space-y-4">
            {/* 공개 범위 */}
            <div>
              <label className="block text-xs text-gray-500 mb-2">공개 범위</label>
              <div className="flex gap-2">
                {([
                  { value: 'private',  icon: '🔒', label: '비공개', desc: '나만 볼 수 있음 (댓글 불가)' },
                  { value: 'unlisted', icon: '🔗', label: '일부공개', desc: '링크로만 접근 (댓글 가능)' },
                  { value: 'public',   icon: '🌍', label: '공개',   desc: '누구나 검색 가능' },
                ] as const).map(v => (
                  <button key={v.value} onClick={() => setPrivacyStatus(v.value)}
                    className={`flex flex-col items-center px-4 py-2.5 rounded-xl text-sm font-medium transition-colors border ${
                      privacyStatus === v.value
                        ? 'bg-purple-700 border-purple-500 text-white'
                        : 'bg-gray-800 border-gray-700 text-gray-400 hover:bg-gray-700'
                    }`}>
                    <span>{v.icon} {v.label}</span>
                    <span className={`text-[10px] mt-0.5 ${privacyStatus === v.value ? 'text-purple-200' : 'text-gray-600'}`}>{v.desc}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* 메타데이터 미리보기 */}
            {project.metadata?.title && (
              <div className="bg-gray-800 rounded-xl p-3">
                <div className="text-xs text-gray-500 mb-1">업로드될 영상 정보</div>
                <div className="font-medium text-white text-sm truncate">{project.metadata.title}</div>
                {project.metadata.description && (
                  <div className="text-xs text-gray-500 mt-1 line-clamp-2">{project.metadata.description.slice(0, 100)}...</div>
                )}
                {project.metadata.tags && project.metadata.tags.length > 0 && (
                  <div className="text-xs text-gray-500 mt-1 truncate">
                    #{project.metadata.tags.slice(0, 5).join(' #')}
                    {project.metadata.tags.length > 5 && ` 외 ${project.metadata.tags.length - 5}개`}
                  </div>
                )}
              </div>
            )}
            {!project.metadata?.title && (
              <div className="text-xs text-yellow-500">⚠ 메타데이터(제목/설명/태그)를 먼저 생성하세요 (4단계)</div>
            )}

            {/* 업로드 버튼 */}
            <div className="grid grid-cols-2 gap-3">
              <button onClick={handleUpload}
                disabled={uploading || project.status === 'uploading' || !project.metadata?.title}
                className="bg-red-600 hover:bg-red-500 disabled:opacity-40 disabled:cursor-not-allowed text-white py-3 rounded-2xl font-bold text-sm transition-colors">
                {project.status === 'uploading' ? '⏳ API 업로드 중...' :
                 yt.video_id                    ? '🔄 재업로드' :
                                                  '🚀 API 업로드'}
              </button>
              <button onClick={async () => {
                const res = await api.youtube.openStudio(project.id)
                // 메타데이터 클립보드 복사
                const meta = `${res.title}\n\n${res.description}\n\n${res.tags?.join(', ')}`
                navigator.clipboard.writeText(meta)
                alert('YouTube Studio + 파일 폴더가 열렸습니다!\n\n1. 폴더에서 MP4를 YouTube에 드래그\n2. 제목/설명은 클립보드에 복사됨 (Ctrl+V)\n3. 업로드 완료 후 여기로 돌아오세요')
              }}
                disabled={!project.metadata?.title}
                className="bg-gray-700 hover:bg-gray-600 disabled:opacity-40 text-white py-3 rounded-2xl font-bold text-sm transition-colors">
                🌐 브라우저로 직접 업로드
              </button>
            </div>
            <p className="text-[10px] text-gray-600 text-center mt-1">API: 자동 업로드 (느림) | 브라우저: 수동 업로드 (빠름, 메타데이터 자동 복사)</p>

            {project.status === 'uploading' && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="w-3 h-3 border-2 border-red-400/30 border-t-red-400 rounded-full animate-spin" />
                    <span className="text-xs text-red-300">YouTube 업로드 중...</span>
                  </div>
                  <span className="text-sm font-mono text-red-300">{uploadProgress}%</span>
                </div>
                <div className="w-full bg-gray-800 rounded-full h-2.5">
                  <div className="bg-red-500 h-2.5 rounded-full transition-all duration-500" style={{ width: `${uploadProgress}%` }} />
                </div>
                <p className="text-[10px] text-gray-600 text-center">대용량 파일은 수 분~수십 분 소요될 수 있습니다</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
