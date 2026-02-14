"""
AI Response Service - Data Models
Why: Falco Alert JSON 구조를 Pydantic으로 정의하여 타입 안정성 확보
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime


class K8sMetadata(BaseModel):
    """Kubernetes metadata from Falco alert"""

    pod_name: Optional[str] = Field(None, alias="pod.name")
    namespace: Optional[str] = Field(None, alias="pod.namespace")
    container_name: Optional[str] = Field(None, alias="container.name")
    container_image: Optional[str] = Field(None, alias="container.image")


class FalcoAlert(BaseModel):
    """
    Falco Alert JSON structure

    Example:
    {
      "priority": "Critical",
      "rule": "Terminal shell in container",
      "time": "2026-02-15T10:30:45Z",
      "output": "A shell was spawned in a container...",
      "output_fields": {
        "container.id": "abc123",
        "container.name": "web",
        "evt.time": "10:30:45",
        "k8s.ns.name": "default",
        "k8s.pod.name": "web-app",
        "proc.cmdline": "/bin/bash",
        "user.name": "root"
      }
    }
    """

    priority: str
    rule: str
    time: str
    output: str
    output_fields: Dict[str, Any]

    # Extracted k8s metadata
    @property
    def namespace(self) -> str:
        """Extract namespace from output_fields"""
        return self.output_fields.get("k8s.ns.name", "unknown")

    @property
    def pod_name(self) -> str:
        """Extract pod name from output_fields"""
        return self.output_fields.get("k8s.pod.name", "unknown")

    @property
    def container_name(self) -> str:
        """Extract container name from output_fields"""
        return self.output_fields.get("container.name", "unknown")

    @property
    def user_name(self) -> str:
        """Extract user name from output_fields"""
        return self.output_fields.get("user.name", "unknown")

    @property
    def process_cmdline(self) -> str:
        """Extract process command line from output_fields"""
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

    alert: FalcoAlert
    analysis: AnalysisResult
    action_taken: str
    success: bool
    error_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    dry_run: bool = False

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
