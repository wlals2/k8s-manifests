"""
AI Response Service - Configuration
Why: 환경 변수 및 설정 중앙 관리
"""

import os
from typing import Optional


class Config:
    """Application Configuration"""

    # API Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Claude API
    CLAUDE_API_KEY: str = os.getenv("CLAUDE_API_KEY", "")
    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
    CLAUDE_MAX_TOKENS: int = int(os.getenv("CLAUDE_MAX_TOKENS", "1024"))

    # Kubernetes
    # Why: InClusterConfig 사용 시 자동 로드, 로컬 테스트 시 KUBECONFIG 사용
    K8S_IN_CLUSTER: bool = os.getenv("K8S_IN_CLUSTER", "true").lower() == "true"

    # Response Policy
    # Why: Risk Score 기준으로 자동 대응 레벨 결정
    RISK_THRESHOLD_MONITOR: int = int(os.getenv("RISK_THRESHOLD_MONITOR", "0"))
    RISK_THRESHOLD_ISOLATE: int = int(os.getenv("RISK_THRESHOLD_ISOLATE", "50"))
    RISK_THRESHOLD_DELETE: int = int(os.getenv("RISK_THRESHOLD_DELETE", "80"))
    RISK_THRESHOLD_BLOCK: int = int(os.getenv("RISK_THRESHOLD_BLOCK", "95"))

    # Operational Mode
    # Why: Dry-run 모드에서는 AI 분석만 수행, 실제 대응 없음
    DRY_RUN: bool = os.getenv("DRY_RUN", "true").lower() == "true"

    # Discord Webhook (Optional)
    DISCORD_WEBHOOK_URL: Optional[str] = os.getenv("DISCORD_WEBHOOK_URL")

    @classmethod
    def validate(cls) -> None:
        """
        Validate required configuration
        Why: API Key 없이도 서비스 시작 가능 (health check 응답)
             /analyze 호출 시에만 에러 반환
        """
        if not cls.CLAUDE_API_KEY:
            import logging
            logging.getLogger(__name__).warning(
                "CLAUDE_API_KEY is not set. Service will start but /analyze will fail."
            )

    @classmethod
    def get_response_action(cls, risk_score: int) -> str:
        """
        Determine response action based on risk score

        Args:
            risk_score: Risk score (0-100)

        Returns:
            Action: monitor, isolate, delete, block
        """
        if risk_score >= cls.RISK_THRESHOLD_BLOCK:
            return "block"
        elif risk_score >= cls.RISK_THRESHOLD_DELETE:
            return "delete"
        elif risk_score >= cls.RISK_THRESHOLD_ISOLATE:
            return "isolate"
        else:
            return "monitor"


    # Why: AI 판단 결과를 로그로 축적하여 추후 Talon Rule로 변환할 때 활용
    LOG_AI_DECISIONS: bool = os.getenv("LOG_AI_DECISIONS", "true").lower() == "true"
