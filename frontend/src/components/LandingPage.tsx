interface Props {
  onStart: () => void
  onAdmin: () => void
  onGuide: () => void
}

export default function LandingPage({ onStart, onAdmin, onGuide }: Props) {
  const features = [
    { icon: '🎵', title: 'Suno 곡 배치 생성', desc: 'AI 가사 생성부터 다운로드·헤더 교정까지 자동' },
    { icon: '🎬', title: 'CapCut 프로젝트 자동 빌드', desc: '배경·파형·자막 레이어를 합쳐 draft 파일 생성' },
    { icon: '✍️', title: '메타데이터 & 업로드', desc: 'Gemini 로 제목·설명·태그 생성, YouTube Studio 자동 입력' },
  ]

  const steps = [
    '가입 후 관리자 승인을 기다립니다',
    '승인되면 전용 프로그램 설치 파일(exe)을 받습니다',
    '더블클릭으로 설치하면 PC 에 자동 설정됩니다',
    '바탕화면 아이콘으로 언제든 실행',
  ]

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <header className="px-6 py-4 flex items-center justify-between max-w-5xl mx-auto">
        <div className="text-lg font-bold text-purple-400">🎬 Music Outo</div>
        <div className="flex items-center gap-2">
          <button
            onClick={onGuide}
            className="text-sm text-gray-400 hover:text-purple-300 px-3 py-2 transition-colors"
          >
            📖 사용 가이드
          </button>
          <button
            onClick={onStart}
            className="text-sm bg-purple-600 hover:bg-purple-500 text-white px-4 py-2 rounded-lg transition-colors"
          >
            로그인 / 가입
          </button>
        </div>
      </header>

      <section className="max-w-3xl mx-auto px-6 pt-16 pb-20 text-center">
        <h1 className="text-3xl md:text-5xl font-bold mb-5 leading-tight">
          YouTube 플레이리스트 영상
          <br />
          <span className="text-purple-400">처음부터 끝까지 자동으로</span>
        </h1>
        <p className="text-gray-400 text-base md:text-lg mb-10 max-w-xl mx-auto">
          Suno AI 곡 생성 · CapCut 프로젝트 빌드 · YouTube 업로드까지
          한 프로그램 안에서 끝냅니다. 설치 후엔 바탕화면 아이콘 하나면 됩니다.
        </p>
        <button
          onClick={onStart}
          className="bg-purple-600 hover:bg-purple-500 text-white font-semibold px-8 py-4 rounded-xl text-lg transition-colors"
        >
          시작하기 →
        </button>
      </section>

      <section className="max-w-5xl mx-auto px-6 pb-16 grid md:grid-cols-3 gap-5">
        {features.map((f) => (
          <div key={f.title} className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
            <div className="text-3xl mb-3">{f.icon}</div>
            <h3 className="font-semibold text-white mb-2">{f.title}</h3>
            <p className="text-gray-400 text-sm leading-relaxed">{f.desc}</p>
          </div>
        ))}
      </section>

      <section className="max-w-3xl mx-auto px-6 pb-24">
        <h2 className="text-xl font-semibold text-center mb-8">사용 방법</h2>
        <ol className="space-y-3">
          {steps.map((s, i) => (
            <li key={i} className="flex gap-4 items-start bg-gray-900 border border-gray-800 rounded-xl px-5 py-4">
              <span className="shrink-0 w-7 h-7 rounded-full bg-purple-600 text-white text-sm font-bold flex items-center justify-center">
                {i + 1}
              </span>
              <span className="text-gray-300 text-sm pt-0.5">{s}</span>
            </li>
          ))}
        </ol>
      </section>

      <footer className="border-t border-gray-800 px-6 py-6 text-center text-xs text-gray-600">
        <button
          onClick={onAdmin}
          className="text-gray-700 hover:text-gray-500 transition-colors"
        >
          관리자
        </button>
      </footer>
    </div>
  )
}
