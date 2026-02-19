"""
AI Response Service - Main Application
Why: Falco Alert를 수신하여 AI 분석 후 Kubernetes 자동 대응 수행
"""

import logging
import sys
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
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

# Initialize FastAPI app
app = FastAPI(
    title="AI Response Service",
    description="AI-driven security incident auto-response system",
    version="1.0.0",
)

# Initialize components
analyzer = ClaudeAnalyzer()
responder = K8sResponder()


@app.get("/health")
async def health_check():
    """
    Health check endpoint

    Why: Kubernetes liveness/readiness probe용
    """
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/")
async def root():
    """
    Root endpoint
    """
    return {
        "service": "AI Response Service",
        "version": "1.0.0",
        "dry_run": Config.DRY_RUN,
        "endpoints": {
            "analyze": "/analyze (POST)",
            "health": "/health (GET)",
            "stats": "/stats (GET)",
        },
    }


@app.post("/analyze")
async def analyze_alert(
    alert: FalcoAlert, background_tasks: BackgroundTasks
) -> ResponseResult:
    """
    Analyze Falco alert and execute auto-response

    Args:
        alert: Falco alert JSON

    Returns:
        ResponseResult: Analysis and response result

    Why: Falco Sidekick에서 호출하는 메인 엔드포인트
    """
    logger.info(f"Received Falco alert: {alert.rule} (Priority: {alert.priority})")
    logger.debug(f"Alert details: {alert.dict()}")

    try:
        # Step 1: AI Analysis
        logger.info("Analyzing alert with Claude API...")
        analysis = analyzer.analyze_alert(alert)
        logger.info(
            f"AI Analysis complete: Risk={analysis.risk_score}, Action={analysis.action}, Attack={analysis.is_attack}"
        )

        # Step 2: Determine action based on config
        recommended_action = Config.get_response_action(analysis.risk_score)
        final_action = analysis.action  # Use AI's recommendation

        logger.info(
            f"Recommended action: {recommended_action}, AI action: {final_action}"
        )

        # Step 3: Execute response
        success = False
        error_message = None

        try:
            success = await execute_response(
                alert, final_action, dry_run=Config.DRY_RUN
            )
        except Exception as e:
            logger.error(f"Failed to execute response: {e}")
            error_message = str(e)

        # Step 4: Build result
        result = ResponseResult(
            alert=alert,
            analysis=analysis,
            action_taken=final_action if success else "none",
            success=success,
            error_message=error_message,
            dry_run=Config.DRY_RUN,
        )

        # Step 5: Send Discord notification (background)
        if Config.DISCORD_WEBHOOK_URL:
            background_tasks.add_task(send_discord_notification, result)

        # Step 6: Log result
        logger.info(
            f"Response complete: Action={result.action_taken}, Success={result.success}"
        )

        return result

    except Exception as e:
        logger.error(f"Unexpected error in /analyze endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def execute_response(alert: FalcoAlert, action: str, dry_run: bool) -> bool:
    """
    Execute response action

    Args:
        alert: Falco alert
        action: Response action (monitor/isolate/delete/block)
        dry_run: Dry-run mode

    Returns:
        bool: Success

    Why: 액션별로 적절한 Kubernetes 대응 실행
    """
    namespace = alert.namespace
    pod_name = alert.pod_name

    logger.info(
        f"{'[DRY-RUN] ' if dry_run else ''}Executing action: {action} on {namespace}/{pod_name}"
    )

    if action == "monitor":
        # Monitor: Log only
        logger.info(f"Action=monitor: Logging only, no response taken")
        return True

    elif action == "isolate":
        # Isolate: Create NetworkPolicy
        return responder.isolate_pod(namespace, pod_name, dry_run=dry_run)

    elif action == "delete":
        # Delete: Remove pod
        return responder.delete_pod(namespace, pod_name, dry_run=dry_run)

    elif action == "block":
        # Block: IP blocking (not implemented yet)
        logger.warning(f"Action=block requested but not implemented yet")
        # Fallback to isolate
        return responder.isolate_pod(namespace, pod_name, dry_run=dry_run)

    else:
        logger.error(f"Unknown action: {action}")
        return False


async def send_discord_notification(result: ResponseResult):
    """
    Send Discord notification

    Args:
        result: Response result

    Why: Discord 알람으로 사후 검토 가능
    """
    if not Config.DISCORD_WEBHOOK_URL:
        return

    try:
        # Build Discord embed
        embed = {
            "title": "🤖 AI Auto-Response",
            "color": _get_embed_color(result.analysis.risk_score),
            "fields": [
                {"name": "📋 Alert", "value": result.alert.rule, "inline": False},
                {
                    "name": "🎯 Target",
                    "value": f"{result.alert.namespace}/{result.alert.pod_name}",
                    "inline": True,
                },
                {
                    "name": "📊 Risk Score",
                    "value": f"{result.analysis.risk_score}/100",
                    "inline": True,
                },
                {
                    "name": "⚡ Action",
                    "value": result.action_taken.upper(),
                    "inline": True,
                },
                {"name": "💡 Reason", "value": result.analysis.reason, "inline": False},
                {
                    "name": "✅ Success",
                    "value": "Yes" if result.success else "No",
                    "inline": True,
                },
                {
                    "name": "🧪 Mode",
                    "value": "DRY-RUN" if result.dry_run else "LIVE",
                    "inline": True,
                },
            ],
            "timestamp": result.timestamp.isoformat(),
            "footer": {"text": "AI Response Service"},
        }

        if result.error_message:
            embed["fields"].append(
                {"name": "❌ Error", "value": result.error_message, "inline": False}
            )

        # Send to Discord
        async with httpx.AsyncClient() as client:
            response = await client.post(
                Config.DISCORD_WEBHOOK_URL,
                json={"embeds": [embed]},
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info("Discord notification sent successfully")

    except Exception as e:
        logger.error(f"Failed to send Discord notification: {e}")


def _get_embed_color(risk_score: int) -> int:
    """
    Get Discord embed color based on risk score

    Why: 위험도에 따라 시각적으로 구분
    """
    if risk_score >= 80:
        return 0xFF0000  # Red
    elif risk_score >= 50:
        return 0xFFA500  # Orange
    elif risk_score >= 30:
        return 0xFFFF00  # Yellow
    else:
        return 0x00FF00  # Green


@app.get("/stats")
async def get_stats():
    """
    Get service statistics

    Why: 모니터링 및 디버깅용
    """
    # TODO: Implement statistics tracking
    # - Total alerts processed
    # - Actions taken (monitor/isolate/delete/block)
    # - Average risk score
    # - Response time
    return {
        "status": "not_implemented",
        "message": "Statistics tracking will be added in future version",
    }


if __name__ == "__main__":
    logger.info(f"Starting AI Response Service on {Config.HOST}:{Config.PORT}")
    logger.info(f"Dry-run mode: {Config.DRY_RUN}")
    logger.info(f"Claude model: {Config.CLAUDE_MODEL}")

    uvicorn.run(
        "main:app",
        host=Config.HOST,
        port=Config.PORT,
        log_level=Config.LOG_LEVEL.lower(),
    )
