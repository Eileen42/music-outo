import { useEffect, useState } from 'react'
import type { Project } from '../types'
import { api } from '../api/client'

interface Props {
  project: Project
  onRefresh: () => void
}

export default function YouTubeUpload({ project, onRefresh }: Props) {
  const [authorized, setAuthorized] = useState(false)
  const [authUrl, setAuthUrl] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [privacyStatus, setPrivacyStatus] = useState('private')
  const [loading, setLoading] = useState(true)

  const yt = project.youtube || { video_id: null, url: null, uploaded_at: null }
  const buildDone = project.build?.status === 'done'

  useEffect(() => {
    api.youtube.status().then((s: { authorized: boolean }) => {
      setAuthorized(s.authorized)
      setLoading(false)
    })
    const params = new URLSearchParams(window.location.search)
    if (params.get('youtube_auth') === 'success') {
      setAuthorized(true)
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])

  useEffect(() => {
    if (project.status !== 'uploading') return
    const interval = setInterval(async () => {
      const s = await api.youtube.uploadStatus(project.id)
      if (s.status !== 'uploading') {
        await onRefresh()
        clearInterval(interval)
      }
    }, 3000)
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
      {/* 빌드 미완료 경고 */}
      {!buildDone && (
        <div className="bg-yellow-950/40 border border-yellow-800 rounded-2xl p-4 mb-5 flex gap-3">
          <span className="text-yellow-500 text-lg shrink-0">⚠️</span>
          <div>
            <div className="text-yellow-300 font-semibold text-sm mb-0.5">빌드가 필요합니다</div>
            <div className="text-yellow-600 text-xs">6단계 '빌드 & 다운로드'에서 먼저 영상을 만들어야 YouTube에 업로드할 수 있습니다.</div>
          </div>
        </div>
      )}

      {/* 업로드 완료 */}
      {yt.video_id && (
        <div className="bg-green-950/40 border border-green-700 rounded-2xl p-4 mb-5">
          <div className="text-green-400 font-semibold text-sm mb-2">✅ YouTube 업로드 완료</div>
          <a
            href={yt.url || `https://www.youtube.com/watch?v=${yt.video_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-400 hover:text-blue-300 hover:underline text-sm break-all"
          >
            {yt.url || `https://www.youtube.com/watch?v=${yt.video_id}`}
          </a>
          {yt.uploaded_at && (
            <div className="text-xs text-gray-600 mt-1.5">
              업로드 시각: {new Date(yt.uploaded_at).toLocaleString('ko-KR')}
            </div>
          )}
        </div>
      )}

      {/* STEP 1: Google 계정 연결 */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 mb-4">
        <div className="flex items-center gap-2 mb-1">
          <span className="w-5 h-5 rounded-full bg-gray-700 text-gray-400 text-xs flex items-center justify-center font-bold shrink-0">1</span>
          <h3 className="text-sm font-semibold text-gray-200">Google 계정 연결</h3>
        </div>
        <p className="text-xs text-gray-600 mb-4 ml-7">YouTube 채널에 업로드하려면 Google 계정 인증이 필요합니다.</p>

        {authorized ? (
          <div className="ml-7 flex items-center gap-3">
            <span className="text-green-400 text-sm font-medium">✅ 인증 완료</span>
            <button
              onClick={handleRevoke}
              className="text-xs text-gray-600 hover:text-red-400 transition-colors"
            >
              연결 해제
            </button>
          </div>
        ) : (
          <div className="ml-7 flex flex-col gap-3">
            {!authUrl ? (
              <button
                onClick={handleGetAuthUrl}
                className="self-start bg-red-700 hover:bg-red-600 text-white px-5 py-2.5 rounded-xl text-sm font-semibold transition-colors"
              >
                🔑 Google 계정 로그인
              </button>
            ) : (
              <div>
                <p className="text-xs text-gray-400 mb-2">
                  아래 버튼으로 Google 로그인 페이지를 열고, 권한을 허용하세요.
                  완료되면 자동으로 돌아옵니다.
                </p>
                <button
                  onClick={() => window.open(authUrl, '_blank', 'width=600,height=700')}
                  className="bg-red-700 hover:bg-red-600 text-white px-5 py-2.5 rounded-xl text-sm font-semibold transition-colors"
                >
                  🌐 Google 로그인 창 열기
                </button>
                <p className="text-xs text-gray-600 mt-2">
                  로그인 후 자동으로 인증됩니다. 안 되면{' '}
                  <button onClick={() => window.location.reload()} className="text-blue-400 hover:underline">새로고침</button>
                  하세요.
                </p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* STEP 2: 업로드 설정 */}
      {authorized && buildDone && (
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5">
          <div className="flex items-center gap-2 mb-1">
            <span className="w-5 h-5 rounded-full bg-gray-700 text-gray-400 text-xs flex items-center justify-center font-bold shrink-0">2</span>
            <h3 className="text-sm font-semibold text-gray-200">업로드 설정</h3>
          </div>
          <p className="text-xs text-gray-600 mb-4 ml-7">공개 범위를 선택하고 업로드를 시작하세요.</p>

          <div className="ml-7 space-y-4">
            {/* 공개 범위 */}
            <div>
              <label className="block text-xs text-gray-500 mb-2">공개 범위</label>
              <div className="flex gap-2">
                {([
                  { value: 'private',  icon: '🔒', label: '비공개', desc: '나만 볼 수 있음' },
                  { value: 'unlisted', icon: '🔗', label: '미등록', desc: '링크 있으면 볼 수 있음' },
                  { value: 'public',   icon: '🌍', label: '공개',   desc: '누구나 볼 수 있음' },
                ] as const).map(v => (
                  <button
                    key={v.value}
                    onClick={() => setPrivacyStatus(v.value)}
                    className={`flex flex-col items-center px-4 py-2.5 rounded-xl text-sm font-medium transition-colors border ${
                      privacyStatus === v.value
                        ? 'bg-purple-700 border-purple-500 text-white'
                        : 'bg-gray-800 border-gray-700 text-gray-400 hover:bg-gray-700'
                    }`}
                  >
                    <span>{v.icon} {v.label}</span>
                    <span className={`text-[10px] mt-0.5 ${privacyStatus === v.value ? 'text-purple-200' : 'text-gray-600'}`}>
                      {v.desc}
                    </span>
                  </button>
                ))}
              </div>
            </div>

            {/* 메타데이터 미리보기 */}
            {project.metadata?.title && (
              <div className="bg-gray-800 rounded-xl p-3">
                <div className="text-xs text-gray-500 mb-1">업로드될 영상 정보</div>
                <div className="font-medium text-white text-sm truncate">{project.metadata.title}</div>
                {project.metadata.tags?.length > 0 && (
                  <div className="text-xs text-gray-500 mt-1 truncate">
                    #{project.metadata.tags.slice(0, 5).join(' #')}
                    {project.metadata.tags.length > 5 && ` 외 ${project.metadata.tags.length - 5}개`}
                  </div>
                )}
              </div>
            )}

            {/* 업로드 버튼 */}
            <button
              onClick={handleUpload}
              disabled={uploading || project.status === 'uploading'}
              className="w-full bg-red-600 hover:bg-red-500 disabled:opacity-40 disabled:cursor-not-allowed text-white py-3.5 rounded-2xl font-bold text-base transition-colors"
            >
              {project.status === 'uploading' ? '⏳ 업로드 중...' :
               yt.video_id                    ? '🔄 재업로드' :
                                                '🚀 YouTube에 업로드'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
