import { useEffect, useState } from 'react'
import type { Project } from '../types'
import { api } from '../api/client'

interface Props {
  project: Project
  onRefresh: () => void
}

export default function BuildDownload({ project, onRefresh }: Props) {
  const [triggering, setTriggering] = useState(false)
  const build = project.build || { status: null, progress: 0, output_file: null, capcut_file: null, error: null }

  useEffect(() => {
    if (build.status !== 'processing') return
    const interval = setInterval(async () => {
      const status = await api.build.status(project.id)
      if (status.status !== 'processing') {
        await onRefresh()
        clearInterval(interval)
      }
    }, 2000)
    return () => clearInterval(interval)
  }, [build.status, project.id, onRefresh])

  const handleBuild = async () => {
    if (!confirm('빌드를 시작하시겠습니까?\n오디오를 병합하고 영상을 합성합니다. 트랙 수에 따라 시간이 걸릴 수 있습니다.')) return
    setTriggering(true)
    try {
      await api.build.trigger(project.id)
      await onRefresh()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } }; message?: string })
      alert('빌드 시작 실패: ' + (msg?.response?.data?.detail || msg?.message || '알 수 없는 오류'))
    } finally {
      setTriggering(false)
    }
  }

  const checks = [
    {
      label: '🎵 트랙',
      ok: project.tracks.length > 0,
      msg: project.tracks.length > 0 ? `${project.tracks.length}개 준비됨` : '트랙을 추가하세요 (필수)',
    },
    {
      label: '🖼️ 배경 이미지',
      ok: !!(project.images?.background || project.images?.thumbnail),
      msg: project.images?.background
        ? '배경 이미지 설정됨'
        : project.images?.thumbnail
        ? '썸네일을 배경으로 사용'
        : '없음 (검은 배경으로 빌드)',
    },
    {
      label: '✍️ 메타데이터',
      ok: !!project.metadata?.title,
      msg: project.metadata?.title ? '제목 있음' : '없음 (YouTube 업로드 시 필요)',
    },
  ]

  const isProcessing = build.status === 'processing'
  const isDone = build.status === 'done'
  const isError = build.status === 'error'

  return (
    <div>
      {/* 빌드 전 체크리스트 */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 mb-4">
        <h3 className="text-sm font-semibold text-gray-200 mb-1">빌드 전 체크리스트</h3>
        <p className="text-xs text-gray-600 mb-4">아래 항목을 확인하고 빌드를 시작하세요.</p>
        <div className="space-y-2.5">
          {checks.map(c => (
            <div key={c.label} className="flex items-center gap-3">
              <span className={`shrink-0 w-5 h-5 flex items-center justify-center rounded-full text-xs font-bold ${
                c.ok ? 'bg-green-700 text-white' : 'bg-gray-800 text-gray-600 border border-gray-700'
              }`}>
                {c.ok ? '✓' : '○'}
              </span>
              <span className={`text-sm ${c.ok ? 'text-gray-200' : 'text-gray-500'}`}>{c.label}</span>
              <span className={`text-xs ml-auto ${c.ok ? 'text-gray-500' : 'text-yellow-600'}`}>{c.msg}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 빌드 상태 */}
      {build.status && (
        <div className={`rounded-2xl p-5 mb-4 border ${
          isError ? 'bg-red-950/30 border-red-800' :
          isDone  ? 'bg-green-950/30 border-green-800' :
                    'bg-yellow-950/30 border-yellow-800'
        }`}>
          {isProcessing && (
            <>
              <div className="flex items-center justify-between mb-3">
                <span className="text-yellow-400 font-semibold text-sm">⚙️ 빌드 진행 중...</span>
                <span className="text-yellow-300 text-sm font-mono">{build.progress}%</span>
              </div>
              <div className="w-full bg-gray-800 rounded-full h-2.5">
                <div
                  className="bg-purple-500 h-2.5 rounded-full transition-all duration-500"
                  style={{ width: `${build.progress}%` }}
                />
              </div>
              <p className="text-xs text-gray-500 mt-2">잠시 기다려주세요. 트랙 수에 따라 수 분이 걸릴 수 있습니다.</p>
            </>
          )}

          {isDone && (
            <div className="text-green-400 font-semibold text-sm">✅ 빌드 완료! 아래에서 다운로드하세요.</div>
          )}

          {isError && (
            <>
              <div className="text-red-400 font-semibold text-sm mb-2">❌ 빌드 실패</div>
              {build.error && (
                <div className="text-red-300 text-xs font-mono bg-gray-900 rounded-lg p-3 overflow-auto">
                  {build.error}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* 다운로드 */}
      {isDone && (
        <div className="bg-gray-900 border border-green-800 rounded-2xl p-5 mb-4">
          <h3 className="text-sm font-semibold text-gray-200 mb-3">📥 결과물 다운로드</h3>
          <div className="flex gap-3 flex-wrap">
            <a
              href={api.build.downloadUrl(project.id)}
              download
              className="flex items-center gap-2 bg-green-700 hover:bg-green-600 text-white px-5 py-2.5 rounded-xl text-sm font-semibold transition-colors"
            >
              🎬 MP4 영상 다운로드
            </a>
            {build.capcut_file && (
              <a
                href={api.build.downloadCapcutUrl(project.id)}
                download
                className="flex items-center gap-2 bg-gray-700 hover:bg-gray-600 text-white px-5 py-2.5 rounded-xl text-sm font-semibold transition-colors"
              >
                ✂️ CapCut 프로젝트 파일
              </a>
            )}
          </div>
        </div>
      )}

      {/* 빌드 버튼 */}
      <button
        onClick={handleBuild}
        disabled={triggering || isProcessing || project.tracks.length === 0}
        className={`w-full py-3.5 rounded-2xl font-bold text-base transition-colors ${
          isProcessing || triggering
            ? 'bg-gray-700 text-gray-400 cursor-not-allowed'
            : project.tracks.length === 0
            ? 'bg-gray-800 text-gray-600 cursor-not-allowed'
            : isDone
            ? 'bg-gray-700 hover:bg-gray-600 text-white'
            : 'bg-purple-600 hover:bg-purple-500 text-white'
        }`}
      >
        {isProcessing ? '⏳ 빌드 중...' :
         triggering   ? '⏳ 시작 중...' :
         isDone       ? '🔄 다시 빌드' :
                        '🚀 빌드 시작'}
      </button>

      {project.tracks.length === 0 && (
        <p className="text-xs text-gray-600 text-center mt-2">트랙을 먼저 추가해야 빌드할 수 있습니다.</p>
      )}
    </div>
  )
}
