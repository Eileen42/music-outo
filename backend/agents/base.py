"""
에이전트 베이스 클래스.
각 에이전트는 스킬 파일(.md)을 로드하여 장르별 전문 지식을 활용한다.

장르 매칭은 _aliases.json 을 우선 참조하므로 사용자가 한글 ("K-팝", "케이팝",
"클래식 록") / 영문 ("kpop", "Classic Rock") / 변형 ("K팝") 어떻게 입력해도
정규 ID 로 자동 매핑된다.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from core.gemini_client import gemini_client

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent.parent / "templates" / "skills"
_PROMPTS_DIR = Path(__file__).parent.parent / "templates" / "prompts"
_ALIASES_FILE = _SKILLS_DIR / "_aliases.json"


def _normalize_alias_key(s: str) -> str:
    """별칭 매칭용 정규화: 소문자 + 공백/하이픈/언더스코어 제거."""
    return s.strip().lower().replace(" ", "").replace("-", "").replace("_", "")


def _load_aliases_cached() -> dict[str, str]:
    """_aliases.json 을 한 번 로드해 캐싱. 없으면 빈 dict.

    매핑 형태: { 정규화_키 : 영문_id }
    예: { "k팝": "kpop", "kpop": "kpop", "케이팝": "kpop", ... }
    """
    if not _ALIASES_FILE.exists():
        return {}
    try:
        return json.loads(_ALIASES_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"_aliases.json 로드 실패: {e}")
        return {}


_ALIASES: dict[str, str] = _load_aliases_cached()


def resolve_genre_id(user_input: str) -> str | None:
    """사용자가 입력한 장르 문자열 → 정규 ID 변환.

    매칭 안 되면 None — 호출자가 default 처리.
    """
    if not user_input:
        return None
    key = _normalize_alias_key(user_input)
    return _ALIASES.get(key)


class BaseAgent:
    """모든 에이전트의 베이스."""

    name: str = "base"

    def _load_skill(self, genre: str) -> str:
        """장르에 맞는 스킬 파일 로드.

        매칭 우선순위:
          1. _aliases.json 에서 한글/영문 변형 → 정규 ID
          2. 정규 ID 의 .md 파일
          3. (백워드 호환) 사용자 입력을 그대로 정규화한 파일명
          4. default.md 폴백
        """
        skill_dir = _SKILLS_DIR / self.name

        # 1. 별칭 테이블 우선 (한글/영문 변형 자동 매칭)
        canonical_id = resolve_genre_id(genre)
        if canonical_id:
            skill_path = skill_dir / f"{canonical_id}.md"
            if skill_path.exists():
                return skill_path.read_text(encoding="utf-8")

        # 2. 별칭 매칭 실패 시 — 사용자 입력 그대로 정규화 시도 (백워드 호환)
        normalized = genre.strip().lower().replace(" ", "_").replace("/", "_")
        skill_path = skill_dir / f"{normalized}.md"
        if skill_path.exists():
            return skill_path.read_text(encoding="utf-8")

        # 3. default 폴백
        default_path = skill_dir / "default.md"
        if default_path.exists():
            return default_path.read_text(encoding="utf-8")

        # 4. 아무것도 없으면 빈 문자열 (load_channel_skills 가 "(장르 스킬 없음)" 으로 처리)
        return ""

    def _load_prompt_template(self, template_name: str) -> str:
        """프롬프트 템플릿 파일 로드."""
        path = _PROMPTS_DIR / template_name
        return path.read_text(encoding="utf-8")

    def load_channel_skills(self, genres: list[str]) -> str:
        """채널의 장르 목록에 맞는 스킬을 모두 로드하여 합친다."""
        skills = []
        for genre in genres:
            skill = self._load_skill(genre)
            if skill:
                skills.append(f"[{genre} 전문 지식]\n{skill}")
        return "\n\n".join(skills) if skills else "(장르 스킬 없음)"

    async def call_gemini(self, prompt: str) -> dict | list:
        """Gemini API 호출 (JSON 응답)."""
        try:
            return await gemini_client.generate_json(prompt)
        except Exception as e:
            logger.error(f"[{self.name}] Gemini 호출 실패: {e}")
            raise

    @classmethod
    def list_available_skills(cls) -> list[dict]:
        """사용 가능한 스킬 파일 목록 반환 (프론트엔드 표시용)."""
        skill_dir = _SKILLS_DIR / cls.name
        if not skill_dir.exists():
            return []

        skills = []
        for f in sorted(skill_dir.glob("*.md")):
            if f.stem == "default":
                continue
            content = f.read_text(encoding="utf-8")
            # 첫 줄에서 제목 추출
            first_line = content.split("\n")[0].strip().lstrip("#").strip()
            # 요약: 처음 200자
            summary = content[:200].replace("\n", " ").strip()
            skills.append({
                "id": f.stem,
                "name": first_line or f.stem,
                "summary": summary,
                "file": f.name,
            })
        return skills
