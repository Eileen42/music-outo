"""
에이전트 베이스 클래스.
각 에이전트는 스킬 파일(.md)을 로드하여 장르별 전문 지식을 활용한다.
"""
from __future__ import annotations

import logging
from pathlib import Path

from core.gemini_client import gemini_client

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent.parent / "templates" / "skills"
_PROMPTS_DIR = Path(__file__).parent.parent / "templates" / "prompts"


class BaseAgent:
    """모든 에이전트의 베이스."""

    name: str = "base"

    def _load_skill(self, genre: str) -> str:
        """장르에 맞는 스킬 파일 로드. 없으면 default.md 사용."""
        skill_dir = _SKILLS_DIR / self.name
        # 장르명 정규화 (공백→언더스코어, 소문자)
        normalized = genre.strip().lower().replace(" ", "_").replace("/", "_")

        # 정확히 일치하는 스킬 파일
        skill_path = skill_dir / f"{normalized}.md"
        if skill_path.exists():
            return skill_path.read_text(encoding="utf-8")

        # default 폴백
        default_path = skill_dir / "default.md"
        if default_path.exists():
            return default_path.read_text(encoding="utf-8")

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
