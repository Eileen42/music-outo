"""
.env 초기 설정 스크립트.
실행: python setup_env.py
"""
import json
import sys
from pathlib import Path

ENV_PATH = Path(__file__).parent / ".env"
EXAMPLE_PATH = Path(__file__).parent / ".env.example"


def ask(prompt: str, default: str = "", secret: bool = False) -> str:
    if default:
        display = f"{prompt} [{default}]: "
    else:
        display = f"{prompt}: "

    if secret:
        import getpass
        value = getpass.getpass(display)
    else:
        value = input(display)

    return value.strip() or default


def main():
    print("=" * 55)
    print("  YouTube Playlist Video Automator — 환경 설정")
    print("=" * 55)

    if ENV_PATH.exists():
        overwrite = ask("\n.env 파일이 이미 있습니다. 덮어쓸까요? (y/N)", default="N")
        if overwrite.lower() != "y":
            print("취소했습니다. 기존 .env를 사용합니다.")
            sys.exit(0)

    print()
    print("[ Gemini API 키 ]")
    print("  Google AI Studio (https://aistudio.google.com/apikey) 에서 발급")
    print("  여러 개 입력 시 쿼터 초과 시 자동으로 다음 키로 전환됩니다.")
    print()

    keys = []
    while True:
        idx = len(keys) + 1
        prompt = f"  Gemini API 키 {idx}번"
        if idx > 1:
            prompt += " (없으면 엔터)"
        key = ask(prompt, secret=True)
        if not key:
            break
        keys.append(key)
        if idx == 1:
            print(f"  ✓ 키 {idx}개 등록됨")

    if not keys:
        print("\n⚠️  Gemini API 키가 없으면 가사/이미지/메타데이터 생성 기능이 동작하지 않습니다.")
        proceed = ask("키 없이 계속할까요? (y/N)", default="N")
        if proceed.lower() != "y":
            sys.exit(0)

    print()
    print("[ 스토리지 경로 ]")
    storage_path = ask("  저장 경로", default="./backend/storage")

    # .env 작성
    gemini_json = json.dumps(keys)

    env_content = f"""# Gemini API Keys (멀티키 로테이션)
GEMINI_API_KEYS={gemini_json}

# Storage (로컬 실행 시)
STORAGE_PATH={storage_path}

# Redis
REDIS_URL=redis://localhost:6379

# Frontend
VITE_API_URL=http://localhost:8000
"""

    ENV_PATH.write_text(env_content, encoding="utf-8")
    print(f"\n✅ .env 생성 완료: {ENV_PATH.absolute()}")

    # 검증
    print()
    print("[ 설정 검증 중... ]")
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent / "backend"))
        from config import settings
        loaded = settings.gemini_api_keys
        print(f"  ✓ Gemini 키 {len(loaded)}개 로드됨")
        print(f"  ✓ 스토리지 경로: {settings.storage_dir}")
    except Exception as e:
        print(f"  ⚠️  검증 실패 (패키지 미설치일 수 있음): {e}")
        print("     pip install -r backend/requirements.txt 후 다시 확인하세요.")

    print()
    print("[ 다음 단계 ]")
    print("  1. pip install -r backend/requirements.txt")
    print("  2. cd backend && uvicorn main:app --reload --port 8000")
    print("  3. http://localhost:8000/docs 에서 API 테스트")
    print()


if __name__ == "__main__":
    main()
