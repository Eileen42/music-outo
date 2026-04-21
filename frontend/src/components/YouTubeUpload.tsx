import { useState } from 'react'
import type { Project } from '../types'
import { api } from '../api/client'

interface Props {
  project: Project
  onRefresh: () => void
}

export default function YouTubeUpload({ project, onRefresh }: Props) {
  const [fillingMeta, setFillingMeta] = useState(false)
  const [fillStep, setFillStep] = useState<string>('')
  const [fillCurrent, setFillCurrent] = useState(0)
  const [fillTotal, setFillTotal] = useState(10)
  const [fillError, setFillError] = useState<string>('')

  // 영상 파일 업로드 폴더 경로 (안내용)
  const uploadFolder = `...\\backend\\storage\\projects\\${project.id}\\outputs`

  return (
    <div>
      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-5 mb-4">
        <div className="flex items-center gap-2 mb-1">
          <span className="w-5 h-5 rounded-full bg-gray-700 text-gray-400 text-xs flex items-center justify-center font-bold shrink-0">1</span>
          <h3 className="text-sm font-semibold text-gray-200">브라우저 업로드</h3>
          <span className="text-[10px] text-green-400 bg-green-900/30 px-1.5 py-0.5 rounded ml-1">Google 연동 불필요</span>
        </div>
        <div className="ml-7 space-y-3">
          <p className="text-xs text-gray-500">
            YouTube Studio 를 브라우저로 열어 직접 업로드합니다. 메타데이터(제목/설명/태그)는 자동 입력됩니다.
          </p>

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

          <div className="grid grid-cols-2 gap-3">
            <button onClick={async () => {
              await api.youtube.openStudio(project.id)
              alert('YouTube 업로드 페이지 + 파일 폴더가 열렸습니다!\n\n1. 폴더에서 MP4 를 YouTube 에 드래그\n2. 업로드 시작되면 "메타데이터 자동 입력" 클릭')
            }}
              className="bg-gray-700 hover:bg-gray-600 text-white py-3 rounded-2xl font-bold text-sm transition-colors">
              🌐 브라우저 업로드 열기
            </button>
            <button onClick={async () => {
              setFillingMeta(true)
              setFillStep('시작 중...')
              setFillCurrent(0)
              setFillTotal(10)
              setFillError('')
              try {
                await api.youtube.fillMetadata(project.id)
              } catch (err) {
                const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '시작 실패'
                setFillError(detail)
                setFillingMeta(false)
                return
              }
              const startedAt = Date.now()
              const poll = setInterval(async () => {
                try {
                  const p = await api.youtube.fillProgress(project.id)
                  setFillStep(p.step || '진행 중')
                  setFillCurrent(p.current || 0)
                  setFillTotal(p.total || 10)
                  if (p.error) setFillError(p.error)
                  if (p.done) {
                    clearInterval(poll)
                    await onRefresh()
                    setTimeout(() => setFillingMeta(false), 3000)
                  }
                } catch {
                  // 폴링 중 일시 실패는 무시
                }
                if (Date.now() - startedAt > 600000) {
                  clearInterval(poll)
                  setFillingMeta(false)
                }
              }, 2000)
            }}
              disabled={fillingMeta}
              className="bg-indigo-700 hover:bg-indigo-600 disabled:opacity-50 text-white py-3 rounded-2xl font-bold text-sm transition-colors">
              {fillingMeta ? `⏳ ${fillCurrent}/${fillTotal} — ${fillStep}` : '✍️ 메타데이터 자동 입력'}
            </button>
          </div>

          {fillingMeta && (
            <div className="space-y-1.5">
              <div className="w-full bg-gray-800 rounded-full h-1.5">
                <div
                  className="bg-indigo-500 h-1.5 rounded-full transition-all duration-300"
                  style={{ width: `${Math.min(100, Math.round((fillCurrent / Math.max(1, fillTotal)) * 100))}%` }}
                />
              </div>
              <p className={`text-[11px] text-center ${fillError ? 'text-red-400' : 'text-gray-400'}`}>
                {fillError ? `⚠ ${fillError}` : `${fillStep}…`}
              </p>
            </div>
          )}

          {(project as unknown as { browser_metadata_filled?: boolean }).browser_metadata_filled && (
            <div className="bg-green-950/40 border border-green-800 rounded-xl p-3">
              <p className="text-xs text-green-400 font-semibold">✅ 메타데이터 입력 + 게시 완료!</p>
              {(project as unknown as { browser_comment_posted?: boolean }).browser_comment_posted && (
                <p className="text-xs text-green-400 mt-1">✅ 댓글도 작성됨</p>
              )}
            </div>
          )}

          <div className="bg-gray-800/50 rounded-xl p-3 space-y-1.5">
            <p className="text-[10px] text-gray-500 font-semibold">워크플로우:</p>
            <div className="flex items-center gap-2 text-[10px] text-gray-400 flex-wrap">
              <span className="bg-indigo-900/50 text-indigo-300 px-1.5 py-0.5 rounded">CapCut 에서 MP4 내보내기</span>
              <span>→</span>
              <span className="bg-gray-700 text-gray-300 px-1.5 py-0.5 rounded">YouTube Studio 열기</span>
              <span>→</span>
              <span className="bg-gray-700 text-gray-300 px-1.5 py-0.5 rounded">MP4 드래그</span>
              <span>→</span>
              <span className="bg-indigo-900/50 text-indigo-300 px-1.5 py-0.5 rounded">메타데이터 자동 입력</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
