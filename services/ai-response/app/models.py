"""
AI Response Service - Data Models
Why: Falcosidekick webhook JSON 구조를 Pydantic으로 정의하여 타입 안정성 확보
"""

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Dict, Any, List
from datetime import datetime


class FalcoAlert(BaseModel):
    """
    Falcosidekick webhook payload 구조

    Why: Falcosidekick이 webhook으로 보내는 실제 JSON과 일치해야 함
         uuid, source, tags, hostname은 Falcosidekick이 추가하는 필드
    """

    # Why: Falcosidekick이 추가 필드를 보내므로 허용 필수 (없으면 422 에러)
    model_config = ConfigDict(extra="allow")

    priority: str
    rule: str
    time: str
    output: str
    output_fields: Dict[str, Any]

    # Why: Falcosidekick이 추가하는 필드들 (AI 분석 시 컨텍스트로 활용)
    uuid: Optional[str] = None
    source: Optional[str] = None
    tags: Optional[List[str]] = None
    hostname: Optional[str] = None

    @property
    def namespace(self) -> str:
        return self.output_fields.get("k8s.ns.name", "unknown")

    @property
    def pod_name(self) -> str:
        return self.output_fields.get("k8s.pod.name", "unknown")

    @property
    def container_name(self) -> str:
        return self.output_fields.get("container.name", "unknown")

    @property
    def container_image(self) -> str:
        repo = self.output_fields.get("container.image.repository", "unknown")
        tag = self.output_fields.get("container.image.tag", "unknown")
        return f"{repo}:{tag}"

    @property
    def user_name(self) -> str:
        return self.output_fields.get("user.name", "unknown")

    @property
    def process_cmdline(self) -> str:
        return self.output_fields.get("proc.cmdline", "unknown")


class AnalysisResult(BaseModel):
    """
    AI Analysis Result from Claude API

    Why: Claude API 응답을 구조화하여 일관된 처리 보장
    """

    risk_score: int = Field(..., ge=0, le=100, description="Risk score (0-100)")
    is_attack: bool = Field(..., description="Is this a real attack?")
    action: str = Field(
        ...,
        description="Recommended action",
        pattern="^(monitor|isolate|delete|block)$",
    )
    reason: str = Field(..., description="Reasoning for the decision")
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Confidence level (0.0-1.0)"
    )


class ResponseResult(BaseModel):
    """
    Response Action Result

    Why: 자동 대응 결과를 기록하여 감사 추적 가능
    """

    # Why: Pydantic v2에서는 model_config으로 설정
    model_config = ConfigDict(extra="allow")

    alert: FalcoAlert
    analysis: AnalysisResult
    action_taken: str
    success: bool
    error_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    dry_run: bool = False
