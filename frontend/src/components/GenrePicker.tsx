/**
 * GenrePicker — 검증된 장르 chip 선택기.
 *
 * 채널 설정 화면에서 사용자가 장르를 직접 타이핑하는 대신, 백엔드의 56개
 * 검증된 장르 목록 (composer 스킬 .md 파일 기반) 에서 클릭으로 추가할 수 있게
 * 한다. 자유 입력도 그대로 유지 — chip 은 보조 도구.
 *
 * Props:
 *   value     — 쉼표 구분 장르 문자열 (예: "재즈, 카페")
 *   onChange  — 새 문자열 (사용자 타이핑 또는 chip 클릭 시)
 *   placeholder — text input placeholder
 */
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'

interface Genre {
  id: string
  kr_name: string
  en_name: string
}

interface Props {
  value: string
  onChange: (next: string) => void
  placeholder?: string
}

export default function GenrePicker({ value, onChange, placeholder }: Props) {
  const [genres, setGenres] = useState<Genre[]>([])
  const [showAll, setShowAll] = useState(false)
  const [filter, setFilter] = useState('')
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    api.channels.listGenres()
      .then(d => setGenres(d.genres))
      .catch(e => setLoadError(e.message || '장르 목록 로드 실패'))
  }, [])

  // 현재 입력된 장르들 (정규화된 set, 중복 추가 방지용)
  const currentSet = useMemo(() => {
    return new Set(
      value.split(',').map(s => s.trim()).filter(Boolean).map(s => s.toLowerCase())
    )
  }, [value])

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return genres
    return genres.filter(
      g => g.kr_name.toLowerCase().includes(q) || g.en_name.toLowerCase().includes(q),
    )
  }, [genres, filter])

  const visible = showAll ? filtered : filtered.slice(0, 12)

  const addGenre = (g: Genre) => {
    const label = g.kr_name
    if (currentSet.has(label.toLowerCase())) return
    const trimmed = value.trim()
    const next = trimmed
      ? (trimmed.endsWith(',') ? `${trimmed} ${label}` : `${trimmed}, ${label}`)
      : label
    onChange(next)
  }

  return (
    <div className="space-y-2">
      <input
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder ?? '예: 재즈, 카페 (또는 아래 chip 클릭)'}
        className="w-full bg-gray-800 text-white rounded-xl px-3 py-2 text-sm border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-600"
      />

      {loadError && (
        <div className="text-xs text-red-400">⚠ {loadError}</div>
      )}

      {!loadError && genres.length > 0 && (
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-2.5">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[11px] text-gray-500">검증된 장르 ({genres.length}개)</span>
            <input
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder="검색"
              className="flex-1 min-w-0 bg-gray-800 text-gray-200 rounded px-2 py-1 text-xs border border-gray-700 focus:outline-none focus:border-indigo-500 placeholder-gray-600"
            />
            <button
              type="button"
              onClick={() => setShowAll(s => !s)}
              className="text-[11px] text-indigo-400 hover:text-indigo-300 shrink-0"
            >
              {showAll ? '접기' : `더보기 (${filtered.length})`}
            </button>
          </div>

          <div className="flex flex-wrap gap-1.5">
            {visible.map(g => {
              const selected = currentSet.has(g.kr_name.toLowerCase())
              return (
                <button
                  key={g.id}
                  type="button"
                  onClick={() => addGenre(g)}
                  disabled={selected}
                  title={g.en_name}
                  className={
                    selected
                      ? 'text-[11px] px-2 py-1 rounded-full bg-indigo-900/50 text-indigo-300 border border-indigo-700/50 cursor-default'
                      : 'text-[11px] px-2 py-1 rounded-full bg-gray-800 text-gray-300 border border-gray-700 hover:bg-indigo-900/30 hover:border-indigo-700 hover:text-indigo-200 transition-colors'
                  }
                >
                  {g.kr_name}
                  {selected && ' ✓'}
                </button>
              )
            })}
            {visible.length === 0 && (
              <span className="text-xs text-gray-500">검색 결과 없음</span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
