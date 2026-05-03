import { useEffect, useState } from 'react'
import { api } from '../../api/client'

export interface RecipeStatus {
  exists: boolean
  action_count?: number
  recorded_at?: string
}

interface ApiError {
  response?: { data?: { detail?: string } }
}

/**
 * Suno 자동화용 사용자 행동 레시피 녹화 상태 + 핸들러.
 *
 * - mount 시 1회 /api/suno/recipe 호출로 기존 레시피 존재 여부 확인
 * - 녹화 중에는 2초 폴링으로 액션 카운트 갱신, auto_done 신호 시 자동 stop
 */
export function useRecipeRecording() {
  const [recipe, setRecipe] = useState<RecipeStatus | null>(null)
  const [recipeRecording, setRecipeRecording] = useState(false)
  const [recipeActionCount, setRecipeActionCount] = useState(0)
  const [recipeMsg, setRecipeMsg] = useState('')

  useEffect(() => {
    api.suno.getRecipe().then(setRecipe).catch(() => setRecipe(null))
  }, [])

  const handleRecordStart = async () => {
    setRecipeMsg('')
    try {
      await api.suno.record.start()
      setRecipeRecording(true)
      setRecipeActionCount(0)
      setRecipeMsg('브라우저가 열렸습니다. 가사→스타일→제목→Create 순서로 시연하세요.')
    } catch (e: unknown) {
      setRecipeMsg((e as ApiError)?.response?.data?.detail ?? '녹화 시작 실패')
    }
  }

  const handleRecordStop = async () => {
    try {
      const res = await api.suno.record.stop()
      setRecipeRecording(false)
      setRecipeMsg(`✅ 레시피 저장 완료 (${res.action_count}개 동작)`)
      const r = await api.suno.getRecipe()
      setRecipe(r)
    } catch (e: unknown) {
      setRecipeMsg((e as ApiError)?.response?.data?.detail ?? '녹화 완료 실패')
    }
  }

  const handleRecordCancel = async () => {
    await api.suno.record.cancel().catch(() => {})
    setRecipeRecording(false)
    setRecipeMsg('')
  }

  const handleDeleteRecipe = async () => {
    await api.suno.deleteRecipe()
    setRecipe({ exists: false })
    setRecipeMsg('')
  }

  // 녹화 중 폴링 — auto_done 시 자동 종료
  useEffect(() => {
    if (!recipeRecording) return
    const timer = setInterval(async () => {
      try {
        const s = await api.suno.record.status()
        setRecipeActionCount(s.action_count)
        if (s.auto_done) {
          clearInterval(timer)
          await handleRecordStop()
        }
      } catch { clearInterval(timer) }
    }, 2000)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recipeRecording])

  return {
    recipe,
    recipeRecording,
    recipeActionCount,
    recipeMsg,
    handleRecordStart,
    handleRecordStop,
    handleRecordCancel,
    handleDeleteRecipe,
  }
}
