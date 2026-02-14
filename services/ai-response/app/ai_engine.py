"""
AI Response Service - AI Analysis Engine
Why: Claude API를 활용하여 Falco Alert의 위험도 분석 및 대응 액션 추천
"""

import json
import logging
from typing import Dict, Any
from anthropic import Anthropic, APIError

from .config import Config
from .models import FalcoAlert, AnalysisResult

logger = logging.getLogger(__name__)


class ClaudeAnalyzer:
    """
    Claude API를 사용한 보안 Alert 분석기

    Why: Rule 기반 시스템보다 유연하게 False Positive 판별 가능
    """

    def __init__(self):
        self.client = Anthropic(api_key=Config.CLAUDE_API_KEY)
        self.model = Config.CLAUDE_MODEL
        self.max_tokens = Config.CLAUDE_MAX_TOKENS

    def analyze_alert(self, alert: FalcoAlert) -> AnalysisResult:
        """
        Falco Alert를 분석하여 위험도와 대응 액션 결정

        Args:
            alert: Falco Alert 객체

        Returns:
            AnalysisResult: 분석 결과 (risk_score, action, reason 등)

        Why: AI가 컨텍스트를 이해하여 실제 공격 여부 판단
        """
        try:
            prompt = self._build_analysis_prompt(alert)
            logger.info(f"Sending alert to Claude API: {alert.rule}")

            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

            # Parse Claude's response
            result_text = response.content[0].text
            logger.debug(f"Claude API response: {result_text}")

            # Extract JSON from response
            result_json = self._extract_json(result_text)

            # Validate and return
            return AnalysisResult(**result_json)

        except APIError as e:
            logger.error(f"Claude API error: {e}")
            # Fallback: High risk score on API error
            return AnalysisResult(
                risk_score=70,
                is_attack=True,
                action="monitor",
                reason=f"AI analysis failed (API error), conservative response. Error: {str(e)}",
                confidence=0.5,
            )
        except Exception as e:
            logger.error(f"Unexpected error in AI analysis: {e}")
            return AnalysisResult(
                risk_score=70,
                is_attack=True,
                action="monitor",
                reason=f"AI analysis failed (unexpected error), conservative response. Error: {str(e)}",
                confidence=0.5,
            )

    def _build_analysis_prompt(self, alert: FalcoAlert) -> str:
        """
        Build analysis prompt for Claude API

        Why: 구조화된 프롬프트로 일관된 응답 보장
        """
        return f"""You are a Kubernetes security expert analyzing Falco runtime security alerts.

# Alert Information
- **Rule**: {alert.rule}
- **Priority**: {alert.priority}
- **Time**: {alert.time}
- **Output**: {alert.output}

# Kubernetes Context
- **Namespace**: {alert.namespace}
- **Pod**: {alert.pod_name}
- **Container**: {alert.container_name}
- **User**: {alert.user_name}
- **Process**: {alert.process_cmdline}

# Full Alert Details
```json
{json.dumps(alert.dict(), indent=2)}
```

# Your Task
Analyze this alert and determine:

1. **Is this a real attack or a false positive?**
   - Consider normal Kubernetes operations (kubectl exec, logs, port-forward)
   - Consider legitimate admin activities
   - Consider application behavior

2. **Risk Score (0-100)**
   - 0-30: Low risk (likely false positive)
   - 31-60: Medium risk (suspicious but uncertain)
   - 61-80: High risk (likely attack)
   - 81-100: Critical risk (confirmed attack)

3. **Recommended Action**
   - `monitor`: Log only, no action
   - `isolate`: Create NetworkPolicy to isolate pod
   - `delete`: Delete the pod immediately
   - `block`: Block IP address with Cilium NetworkPolicy

4. **Reasoning**
   - Explain why this is or isn't an attack
   - Reference specific indicators
   - Consider the Kubernetes context

# Response Format (JSON only, no markdown)
{{
  "risk_score": <0-100>,
  "is_attack": <true|false>,
  "action": "<monitor|isolate|delete|block>",
  "reason": "<detailed reasoning>",
  "confidence": <0.0-1.0>
}}

Respond with ONLY valid JSON, no additional text or markdown formatting.
"""

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """
        Extract JSON from Claude's response

        Why: Claude가 markdown 코드 블록으로 감싸는 경우 처리
        """
        # Remove markdown code blocks if present
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

        # Parse JSON
        return json.loads(text.strip())
