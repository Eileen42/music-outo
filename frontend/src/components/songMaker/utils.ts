// SongMaker 에서 쓰는 순수 헬퍼.
// 로직 함수와 상수만 모은다 — 상태나 React 의존성 없음.

const CATEGORY_ICON: Record<string, string> = {
  morning: '🌅', sleep: '😴', drive: '🚗', focus: '💡',
  relax: '☁️', meditation: '🧘', workout: '💪', cafe: '☕',
  night: '🌙', default: '🎵',
}

export function categoryIcon(cat: string): string {
  return CATEGORY_ICON[cat] || CATEGORY_ICON.default
}

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

/** 백엔드가 /storage/... 처럼 절대경로 url 을 주면 API_BASE 를 prefix. */
export function resolveAudioUrl(url: string): string {
  if (!url) return ''
  if (url.startsWith('http')) return url
  return API_BASE + url
}
