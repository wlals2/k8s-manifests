"""
AI Response Service - Main Application
Why: Falco Alert를 수신하여 AI 분석 후 Kubernetes 자동 대응 수행
     AI 판단 결과를 축적하여 추후 Talon Rule 변환에 활용
"""

import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks
import uvicorn
import httpx
from datetime import datetime

from .config import Config
from .models import FalcoAlert, ResponseResult
from .ai_engine import ClaudeAnalyzer
from .k8s_client import K8sResponder

# Configure logging
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# Why: 전역 변수로 컴포넌트 관리 (lifespan에서 초기화)
analyzer: ClaudeAnalyzer = None
responder: K8sResponder = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Why: startup에서 validate → 에러 메시지가 로그에 남음
         import 시 validate하면 스택 트레이스만 보임
    """
    global analyzer, responder
    logger.info(f"Starting AI Response Service")
    logger.info(f"Dry-run mode: {Config.DRY_RUN}")
    logger.info(f"Claude model: {Config.CLAUDE_MODEL}")
    logger.info(f"Discord webhook: {'configured' if Config.DISCORD_WEBHOOK_URL else 'not configured'}")

    Config.validate()
    analyzer = ClaudeAnalyzer()
    responder = K8sResponder()

    logger.info("All components initialized successfully")
    yield
    logger.info("Shutting down AI Response Service")


app = FastAPI(
    title="AI Response Service",
    description="AI-driven security incident auto-response system",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    """Why: Kubernetes liveness/readiness probe용"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/")
async def root():
    return {
        "service": "AI Response Service",
        "version": "1.0.0",
        "dry_run": Config.DRY_RUN,
        "model": Config.CLAUDE_MODEL,
    }


@app.post("/analyze")
async def analyze_alert(
    alert: FalcoAlert, background_tasks: BackgroundTasks
) -> ResponseResult:
    """
    Falco Sidekick에서 호출하는 메인 엔드포인트

    Why: Alert 수신 → AI 분석 → 자동 대응 → Discord 알람
    """
    logger.info(f"Received alert: rule={alert.rule} priority={alert.priority} ns={alert.namespace} pod={alert.pod_name}")

    try:
        # Step 1: AI Analysis
        analysis = analyzer.analyze_alert(alert)
        logger.info(
            f"AI result: risk={analysis.risk_score} action={analysis.action} attack={analysis.is_attack}"
        )

        # Step 2: Execute response
        success = False
        error_message = None

        try:
            success = await execute_response(
                alert, analysis.action, dry_run=Config.DRY_RUN
            )
        except Exception as e:
            logger.error(f"Response execution failed: {e}")
            error_message = str(e)

        # Step 3: Build result
        result = ResponseResult(
            alert=alert,
            analysis=analysis,
            action_taken=analysis.action if success else "none",
            success=success,
            error_message=error_message,
            dry_run=Config.DRY_RUN,
        )

        # Step 4: Discord notification (background)
        if Config.DISCORD_WEBHOOK_URL:
            background_tasks.add_task(send_discord_notification, result)

        return result

    except Exception as e:
        logger.error(f"Error in /analyze: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def execute_response(alert: FalcoAlert, action: str, dry_run: bool) -> bool:
    """Why: 액션별로 적절한 Kubernetes 대응 실행"""
    namespace = alert.namespace
    pod_name = alert.pod_name
    prefix = "[DRY-RUN] " if dry_run else ""

    logger.info(f"{prefix}Executing: {action} on {namespace}/{pod_name}")

    if action == "monitor":
        return True

    elif action == "isolate":
        return responder.isolate_pod(namespace, pod_name, dry_run=dry_run)

    elif action == "delete":
        return responder.delete_pod(namespace, pod_name, dry_run=dry_run)

    elif action == "block":
        logger.warning("Action=block not implemented, falling back to isolate")
        return responder.isolate_pod(namespace, pod_name, dry_run=dry_run)

    else:
        logger.error(f"Unknown action: {action}")
        return False


async def send_discord_notification(result: ResponseResult):
    """Why: Discord 알람으로 AI 판단 결과와 대응 결과를 사후 검토"""
    if not Config.DISCORD_WEBHOOK_URL:
        return

    try:
        embed = {
            "title": "AI Auto-Response",
            "color": _get_embed_color(result.analysis.risk_score),
            "fields": [
                {"name": "Alert", "value": result.alert.rule, "inline": False},
                {
                    "name": "Target",
                    "value": f"{result.alert.namespace}/{result.alert.pod_name}",
                    "inline": True,
                },
                {
                    "name": "Risk Score",
                    "value": f"{result.analysis.risk_score}/100",
                    "inline": True,
                },
                {
                    "name": "Action",
                    "value": result.action_taken.upper(),
                    "inline": True,
                },
                {"name": "Reason", "value": result.analysis.reason[:1024], "inline": False},
                {
                    "name": "Mode",
                    "value": "DRY-RUN" if result.dry_run else "LIVE",
                    "inline": True,
                },
                {
                    "name": "Attack?",
                    "value": "Yes" if result.analysis.is_attack else "No",
                    "inline": True,
                },
            ],
            "timestamp": result.timestamp.isoformat(),
            "footer": {"text": "AI Response Service v1.0.0"},
        }

        if result.error_message:
            embed["fields"].append(
                {"name": "Error", "value": result.error_message[:1024], "inline": False}
            )

        async with httpx.AsyncClient() as client:
            response = await client.post(
                Config.DISCORD_WEBHOOK_URL,
                json={"embeds": [embed]},
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info("Discord notification sent")

    except Exception as e:
        logger.error(f"Discord notification failed: {e}")


def _get_embed_color(risk_score: int) -> int:
    """Why: 위험도에 따라 시각적으로 구분"""
    if risk_score >= 80:
        return 0xFF0000  # Red
    elif risk_score >= 50:
        return 0xFFA500  # Orange
    elif risk_score >= 30:
        return 0xFFFF00  # Yellow
    else:
        return 0x00FF00  # Green
