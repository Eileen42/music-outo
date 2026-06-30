# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — Music Outo 로컬 단일 EXE 빌드.

빌드:
    pyinstaller build_exe.spec
결과:
    dist/music-outo/music-outo.exe  (onedir 모드 — 의존성 dll 동봉)
"""
from pathlib import Path

ROOT = Path(SPECPATH)
BACKEND = ROOT / 'backend'
FRONTEND_DIST = ROOT / 'frontend' / 'dist'
FFMPEG_DIR = ROOT / 'vendor' / 'ffmpeg'   # ffmpeg.exe, ffprobe.exe (install.bat/수동으로 미리 복사)

# ─── 데이터 파일 ────────────────────────────────────────────────────────────
# (소스, 번들 내 경로)
datas = [
    (str(FRONTEND_DIST), 'frontend_dist'),       # SPA 정적 — main.py 가 sys._MEIPASS/frontend_dist 로 찾음
    (str(BACKEND / 'templates'), 'templates'),   # 에이전트 스킬 .md 파일들
    (str(BACKEND / 'assets'), 'assets'),         # ★ CapCut 드래프트 템플릿/스켈레톤/폰트 — capcut_builder 가 필수로 읽음
]

# ffmpeg/ffprobe 동봉 — 받는 PC 에 ffmpeg 가 없어도 영상 빌드가 되도록.
# run_local.py 가 시작 시 이 폴더를 PATH 앞에 붙여 subprocess "ffmpeg" 호출이 동작.
# (datas 로 넣어 PyInstaller 의 DLL 의존성 분석을 건너뜀 — full static 빌드라 단독 실행됨)
for _exe in ('ffmpeg.exe', 'ffprobe.exe'):
    _p = FFMPEG_DIR / _exe
    if _p.exists():
        datas.append((str(_p), 'ffmpeg'))

# ─── 동적 import 보호 ──────────────────────────────────────────────────────
# uvicorn 이 'main:app' 을 문자열로 import → 정적 분석 실패 방지
# 나머지는 main.py 가 직접 import 하므로 자동 해결되지만 명시적으로 적어둠.
hiddenimports = [
    'main',
    # routes
    'routes.build', 'routes.flow_images', 'routes.images', 'routes.layers',
    'routes.metadata', 'routes.projects', 'routes.tracks', 'routes.youtube',
    'routes.channels', 'routes.track_design', 'routes.suno',
    'routes.ontology_routes',
    # agents (lazy import)
    'agents', 'agents.base', 'agents.composer', 'agents.lyricist',
    'agents.designer', 'agents.meta_designer', 'agents.meta_writer',
    'agents.meta_qa', 'agents.suno_qa', 'agents.suno_creator',
    'agents.suno_collector',
    # core (lazy import)
    'core.suno_api', 'core.waveform_generator', 'core.metadata_generator',
    'core.audio_pipeline', 'core.lyrics_sync', 'core.visual_generator',
    'core.track_designer', 'core.gemini_client', 'core.state_manager',
    'core.packager', 'core.channel_profile', 'core.ontology',
    # Suno 배치 runner (frozen 환경에선 subprocess 대신 직접 import 호출)
    '_suno_cookie_runner', '_suno_batch_runner',
    # uvicorn 내부 (문자열 import)
    'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto',
    'uvicorn.protocols', 'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto', 'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
    'uvicorn.protocols.websockets.websockets_impl',
    'uvicorn.lifespan', 'uvicorn.lifespan.on',
]

# ─── 무거워서 일단 제외 (lazy 다운 또는 외부 바이너리로 처리) ───────────────
# faster-whisper / librosa / soundfile 은 음악 파이프라인이 사용하므로 포함.
# playwright 브라우저 바이너리는 별도 (사용자 PC 에 처음 1회 자동 다운).
# ffmpeg.exe 는 외부 바이너리 (PATH 또는 처음 1회 다운).
excludes = [
    'tkinter',     # 안 씀
    'matplotlib',  # 안 씀
    'IPython',
    'jupyter',
]

block_cipher = None

a = Analysis(
    [str(BACKEND / 'run_local.py')],
    pathex=[str(BACKEND)],   # backend/ 를 sys.path 에 — main, routes.* 등 import 가능
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,    # onedir 모드 (단일파일이 아닌 폴더)
    name='music-outo',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,            # 배포용: 검은 콘솔창 없이 트레이 아이콘만 (run_local.py 가 트레이 제공)
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='music-outo',
)
