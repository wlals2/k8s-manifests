#!/usr/bin/env python3
# -------------------------------------------------------------------
# Wazuh Integration: Discord Webhook
# Purpose: Level 10+ 보안 이벤트를 Discord로 실시간 전송
# Why: Wazuh가 탐지한 심각한 보안 이벤트(Reverse Shell, Container Escape 등)를
#      즉시 알림받아야 대응할 수 있기 때문
#
# Dependency: Wazuh Manager 내장 Python + requests 모듈
# Trigger: ossec.conf <integration> 블록에서 level >= 10일 때 호출
# -------------------------------------------------------------------

import json
import os
import sys
from datetime import datetime, timezone

ERR_NO_REQUEST_MODULE = 1
ERR_BAD_ARGUMENTS = 2
ERR_FILE_NOT_FOUND = 6
ERR_INVALID_JSON = 7

try:
    import requests
except Exception:
    print("No module 'requests' found. Install: pip install requests")
    sys.exit(ERR_NO_REQUEST_MODULE)

debug_enabled = False
pwd = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
LOG_FILE = f'{pwd}/logs/integrations.log'

ALERT_INDEX = 1
WEBHOOK_INDEX = 3

# Why: Level별 색상으로 Discord Embed에서 심각도를 시각적으로 구분
LEVEL_COLORS = {
    'critical': 0xFF0000,   # 빨강 (Level 13-15)
    'high': 0xFF6600,       # 주황 (Level 10-12)
    'medium': 0xFFCC00,     # 노랑 (Level 7-9)
    'low': 0x00CC00,        # 녹색 (Level 0-6)
}

# Why: MITRE ATT&CK 전술별 이모지로 공격 유형을 빠르게 식별
MITRE_EMOJI = {
    'Initial Access': '\U0001f6aa',
    'Execution': '\u2699\ufe0f',
    'Persistence': '\U0001f4cc',
    'Privilege Escalation': '\u26a1',
    'Defense Evasion': '\U0001f575\ufe0f',
    'Credential Access': '\U0001f511',
    'Discovery': '\U0001f50d',
    'Lateral Movement': '\u27a1\ufe0f',
    'Collection': '\U0001f4e6',
    'Exfiltration': '\U0001f4e4',
    'Command and Control': '\U0001f3af',
    'Impact': '\U0001f4a5',
}


def main(args):
    global debug_enabled
    try:
        bad_arguments = False
        if len(args) >= 4:
            msg = '{0} {1} {2} {3} {4}'.format(
                args[1], args[2], args[3],
                args[4] if len(args) > 4 else '',
                args[5] if len(args) > 5 else ''
            )
            debug_enabled = len(args) > 4 and args[4] == 'debug'
        else:
            msg = '# ERROR: Wrong arguments'
            bad_arguments = True

        with open(LOG_FILE, 'a') as f:
            f.write(msg + '\n')

        if bad_arguments:
            debug('# ERROR: Exiting, bad arguments. Inputted: %s' % args)
            sys.exit(ERR_BAD_ARGUMENTS)

        process_args(args)

    except Exception as e:
        debug(str(e))
        raise


def process_args(args):
    debug('# Running Discord integration script')

    alert_file_location = args[ALERT_INDEX]
    webhook = args[WEBHOOK_INDEX]

    json_alert = get_json_alert(alert_file_location)
    debug(f"# Alert loaded: {json_alert.get('rule', {}).get('description', 'N/A')}")

    msg = generate_msg(json_alert)

    if not msg:
        debug('# ERROR: Empty message')
        raise Exception('Empty message generated')

    debug('# Sending message to Discord')
    send_msg(msg, webhook)


def get_level_category(level):
    """Alert Level을 심각도 카테고리로 변환"""
    if level >= 13:
        return 'critical'
    elif level >= 10:
        return 'high'
    elif level >= 7:
        return 'medium'
    return 'low'


def generate_msg(alert):
    """Discord Embed 형식의 메시지 생성

    Why: Discord Embed는 Slack Attachment보다 더 풍부한 UI를 제공하고,
         색상/필드/푸터를 활용해 보안 이벤트 정보를 한눈에 파악 가능
    """
    rule = alert.get('rule', {})
    agent = alert.get('agent', {})
    level = rule.get('level', 0)
    category = get_level_category(level)
    color = LEVEL_COLORS.get(category, 0x808080)

    # Title with severity indicator
    severity_label = {
        'critical': '\U0001f6a8 CRITICAL',
        'high': '\u26a0\ufe0f HIGH',
        'medium': '\u26a1 MEDIUM',
        'low': '\u2139\ufe0f LOW',
    }

    title = f"{severity_label.get(category, 'ALERT')} | Level {level}"
    description = rule.get('description', 'No description')

    # Build fields
    fields = []

    # Rule info
    fields.append({
        'name': 'Rule',
        'value': f"ID: {rule.get('id', 'N/A')} | Level: {level}",
        'inline': True
    })

    # Agent info
    if agent:
        fields.append({
            'name': 'Agent',
            'value': f"{agent.get('name', 'N/A')} ({agent.get('id', 'N/A')})",
            'inline': True
        })

    # Location
    location = alert.get('location', 'N/A')
    fields.append({
        'name': 'Location',
        'value': location,
        'inline': True
    })

    # MITRE ATT&CK
    mitre = rule.get('mitre', {})
    if mitre:
        tactics = mitre.get('tactic', [])
        techniques = mitre.get('id', [])

        if tactics:
            tactic_str = ', '.join(
                f"{MITRE_EMOJI.get(t, '')} {t}" for t in tactics
            )
            fields.append({
                'name': 'MITRE Tactic',
                'value': tactic_str,
                'inline': False
            })

        if techniques:
            fields.append({
                'name': 'MITRE Technique',
                'value': ', '.join(techniques),
                'inline': True
            })

    # Rule groups
    groups = rule.get('groups', [])
    if groups:
        fields.append({
            'name': 'Groups',
            'value': ', '.join(groups[:5]),
            'inline': True
        })

    # Full log (truncated)
    full_log = alert.get('full_log', '')
    if full_log:
        # Why: Discord Embed field value 최대 1024자 제한
        if len(full_log) > 500:
            full_log = full_log[:497] + '...'
        fields.append({
            'name': 'Log',
            'value': f"```\n{full_log}\n```",
            'inline': False
        })

    # Timestamp
    timestamp = alert.get('timestamp', datetime.now(timezone.utc).isoformat())

    embed = {
        'title': title,
        'description': description,
        'color': color,
        'fields': fields,
        'footer': {
            'text': 'Wazuh SIEM | Homelab K8s Cluster'
        },
        'timestamp': timestamp
    }

    # Why: Discord Webhook은 embeds 배열 형식을 요구
    payload = {
        'username': 'Wazuh Security',
        'embeds': [embed]
    }

    return json.dumps(payload)


def send_msg(msg, url):
    """Discord Webhook으로 메시지 전송"""
    headers = {'Content-Type': 'application/json'}
    try:
        res = requests.post(url, data=msg, headers=headers, timeout=10)
        debug(f'# Response: {res.status_code}')

        # Why: Discord rate limit (429) 처리
        if res.status_code == 429:
            debug('# WARNING: Discord rate limited')
        elif res.status_code not in (200, 204):
            debug(f'# ERROR: Discord returned {res.status_code}: {res.text}')

    except requests.exceptions.RequestException as e:
        debug(f'# ERROR: Failed to send to Discord: {e}')


def get_json_alert(file_location):
    try:
        with open(file_location) as alert_file:
            return json.load(alert_file)
    except FileNotFoundError:
        debug("# JSON file for alert %s doesn't exist" % file_location)
        sys.exit(ERR_FILE_NOT_FOUND)
    except json.decoder.JSONDecodeError as e:
        debug('Failed getting JSON alert. Error: %s' % e)
        sys.exit(ERR_INVALID_JSON)


def debug(msg):
    if debug_enabled:
        print(msg)
        with open(LOG_FILE, 'a') as f:
            f.write(msg + '\n')


if __name__ == '__main__':
    main(sys.argv)
