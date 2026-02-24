"""
AI Response Service - AI Analysis Engine
Why: Claude API를 활용하여 Falco Alert의 위험도 분석 및 대응 액션 추천
     추후 Talon Rule 변환을 위해 판단 근거를 구조화하여 로깅
"""

import json
import logging
from typing import Dict, Any
from anthropic import Anthropic, APIError

from .config import Config
from .models import FalcoAlert, AnalysisResult

logger = logging.getLogger(__name__)

# Why: AI 분석 결과를 별도 로거로 기록하여 추후 Talon Rule 변환 시 활용
# 이 로그만 grep하면 "어떤 Alert에 어떤 판단을 내렸는지" 한눈에 파악 가능
talon_logger = logging.getLogger("talon_conversion")

SYSTEM_PROMPT = """You are a Kubernetes security expert analyzing Falco runtime security alerts in a homelab environment.

# Environment Context
- Single-user homelab (1 admin)
- Internal network only (192.168.1.0/24)
- Cloudflare protects external traffic
- Kubernetes v1.31 with Cilium CNI and Istio service mesh
- Namespaces: blog-system (web app), security (Wazuh, Falco), monitoring, argocd

# Your Role
Analyze each Falco alert and determine if it's a real attack or false positive.
Consider normal K8s operations (kubectl exec, logs) and legitimate admin activities.

# Response Format (JSON only, no markdown)
{
  "risk_score": <0-100>,
  "is_attack": <true|false>,
  "action": "<monitor|isolate|delete|block>",
  "reason": "<detailed reasoning>",
  "confidence": <0.0-1.0>,
  "talon_rule_hint": {
    "match_rule": "<exact Falco rule name to match>",
    "match_priority": "<minimum priority: WARNING|ERROR|CRITICAL>",
    "match_conditions": "<namespace, image, process 등 추가 조건>",
    "suggested_action": "<Talon action: labelize|networkpolicy|terminate>"
  }
}

The talon_rule_hint field helps convert this AI decision into a static Falco Talon rule later.
Respond with ONLY valid JSON."""


class ClaudeAnalyzer:
    """
    Claude API를 사용한 보안 Alert 분석기

    Why: Rule 기반 시스템보다 유연하게 False Positive 판별 가능
         판단 결과를 축적하여 추후 Talon Rule로 변환
    """

    def __init__(self):
        self.client = Anthropic(api_key=Config.CLAUDE_API_KEY)
        self.model = Config.CLAUDE_MODEL
        self.max_tokens = Config.CLAUDE_MAX_TOKENS

    def analyze_alert(self, alert: FalcoAlert) -> AnalysisResult:
        """
        Falco Alert를 분석하여 위험도와 대응 액션 결정
        """
        try:
            user_prompt = self._build_user_prompt(alert)
            logger.info(f"Sending alert to Claude API: {alert.rule}")

            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )

            result_text = response.content[0].text
            logger.debug(f"Claude API response: {result_text}")

            result_json = self._extract_json(result_text)

            # Why: talon_rule_hint는 AnalysisResult에 포함되지 않으므로 별도 로깅
            talon_hint = result_json.pop("talon_rule_hint", None)
            if talon_hint and Config.LOG_AI_DECISIONS:
                self._log_for_talon_conversion(alert, result_json, talon_hint)

            return AnalysisResult(**result_json)

        except APIError as e:
            logger.error(f"Claude API error: {e}")
            return AnalysisResult(
                risk_score=70,
                is_attack=True,
                action="monitor",
                reason=f"AI analysis failed (API error): {str(e)}",
                confidence=0.5,
            )
        except Exception as e:
            logger.error(f"Unexpected error in AI analysis: {e}")
            return AnalysisResult(
                risk_score=70,
                is_attack=True,
                action="monitor",
                reason=f"AI analysis failed (unexpected): {str(e)}",
                confidence=0.5,
            )

    def _build_user_prompt(self, alert: FalcoAlert) -> str:
        """
        Build user prompt with alert details

        Why: system prompt은 고정, user prompt은 Alert별로 변경
        """
        return f"""Analyze this Falco alert:

Rule: {alert.rule}
Priority: {alert.priority}
Namespace: {alert.namespace}
Pod: {alert.pod_name}
Container: {alert.container_name}
Image: {alert.container_image}
User: {alert.user_name}
Process: {alert.process_cmdline}
Hostname: {alert.hostname or 'unknown'}
MITRE Tags: {', '.join(alert.tags or [])}
Output: {alert.output}

Risk scoring guide:
- 0-30: False positive (normal K8s operation)
- 31-60: Suspicious but uncertain
- 61-80: Likely attack
- 81-100: Confirmed attack"""

    def _log_for_talon_conversion(
        self, alert: FalcoAlert, analysis: dict, talon_hint: dict
    ):
        """
        AI 판단 결과를 Talon Rule 변환용으로 구조화 로깅

        Why: 이 로그를 축적하면 "어떤 패턴에 어떤 대응을 해야 하는지"
             데이터가 쌓이고, 이를 기반으로 Talon Rule을 작성할 수 있음
        """
        talon_logger.info(
            json.dumps(
                {
                    "type": "talon_conversion_data",
                    "falco_rule": alert.rule,
                    "priority": alert.priority,
                    "namespace": alert.namespace,
                    "pod": alert.pod_name,
                    "container_image": alert.container_image,
                    "process": alert.process_cmdline,
                    "ai_risk_score": analysis.get("risk_score"),
                    "ai_action": analysis.get("action"),
                    "ai_is_attack": analysis.get("is_attack"),
                    "ai_confidence": analysis.get("confidence"),
                    "talon_hint": talon_hint,
                },
                ensure_ascii=False,
            )
        )

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """
        Extract JSON from Claude's response

        Why: Claude가 markdown 코드 블록으로 감싸는 경우 처리
        """
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

        return json.loads(text.strip())
