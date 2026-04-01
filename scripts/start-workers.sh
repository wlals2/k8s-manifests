#!/bin/bash
# ==============================================================================
# start-workers.sh - K8s 워커 노드 전체 기동 스크립트
# ==============================================================================
# Purpose: WOL → Windows PC 부팅 → VMware VM 시작 → 노드 Ready 확인
# Usage:   ./start-workers.sh [--dry-run] [--skip-wol] [--setup]
# Why:     vmrun은 비대화형 SSH에서 VMware Authorization 컨텍스트 문제로 실패
#          → Windows Scheduled Task로 인터랙티브 세션에서 실행 (가장 안정적)
# ==============================================================================
# Options:
#   --dry-run    실제 실행 없이 동작 확인
#   --skip-wol   Windows PC가 이미 켜져 있을 때 WOL 생략
#   --setup      최초 1회: Windows PC에 Scheduled Task 등록 (사전 준비)
# ==============================================================================

set -euo pipefail

# ── 색상 ──────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

log()  { echo -e "${BLUE}[$(date +%H:%M:%S)]${NC} $*"; }
ok()   { echo -e "${GREEN}[$(date +%H:%M:%S)] ✅${NC} $*"; }
warn() { echo -e "${YELLOW}[$(date +%H:%M:%S)] ⚠️${NC} $*"; }
err()  { echo -e "${RED}[$(date +%H:%M:%S)] ❌${NC} $*"; }

# ══════════════════════════════════════════════════════════════════════════════
# ⚙️  설정값 (환경에 맞게 수정)
# ══════════════════════════════════════════════════════════════════════════════

# Windows PC
WIN_MAC="B4:2E:99:9E:DC:86"
WIN_IP="192.168.1.195"
WIN_USER="ohjimin"
WIN_SSH_PORT=22

# Why: VMware 폴더명 ≠ K8s 역할명 매핑 (project_discord_agent_bot.md 기준)
declare -A VMS=(
  ["worker1"]="D:\\vmware\\K8s\\K8s-worker\\K8s-worker.vmx"
  ["worker2"]="D:\\vmware\\K8s\\K8s-woker2\\K8s-worker2.vmx"
  ["worker3"]="D:\\vmware\\K8s\\K8s-master\\K8s-master.vmx"
  ["worker4"]="D:\\vmware\\K8s\\k8s-worker4-1\\Clone of k8s-worker4.vmx"
)

# Why: vm_mcp_server.py와 동일한 vm-control.ps1 경로 사용 (일관성)
VM_SCRIPT="C:\\Users\\ohjimin\\Desktop\\vm-scripts\\vm-control.ps1"

# 타임아웃 설정 (초)
WOL_WAIT=90        # Windows PC 부팅 대기
NODE_READY_WAIT=180  # 노드 Ready 대기
NODE_CHECK_INTERVAL=15

# Scheduled Task 이름 (--setup 으로 등록)
TASK_NAME="StartK8sWorkers"

# ══════════════════════════════════════════════════════════════════════════════

DRY_RUN=false
SKIP_WOL=false
SETUP=false

for arg in "$@"; do
  case $arg in
    --dry-run)  DRY_RUN=true ;;
    --skip-wol) SKIP_WOL=true ;;
    --setup)    SETUP=true ;;
    --help)
      sed -n '3,13p' "$0" | sed 's/# //; s/#//'
      exit 0
      ;;
  esac
done

$DRY_RUN && warn "DRY-RUN 모드: 실제 명령 실행 안 함"

# ── 함수: WOL 패킷 전송 ───────────────────────────────────────────────────────
send_wol() {
  local mac="${WIN_MAC//:/-}"
  log "WOL 패킷 전송 → MAC: $WIN_MAC"
  if $DRY_RUN; then warn "[dry-run] wakeonlan $WIN_MAC"; return; fi

  if command -v wakeonlan &>/dev/null; then
    wakeonlan "$WIN_MAC"
  elif command -v etherwake &>/dev/null; then
    sudo etherwake "$WIN_MAC"
  else
    # Python fallback
    python3 -c "
import socket, struct
mac = '${WIN_MAC}'.replace(':', '')
payload = bytes.fromhex('FF' * 6 + mac * 16)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
s.sendto(payload, ('255.255.255.255', 9))
s.close()
print('WOL 전송 완료')
"
  fi
}

# ── 함수: Windows PC SSH 응답 대기 ───────────────────────────────────────────
wait_for_windows() {
  log "Windows PC SSH 응답 대기 중 (최대 ${WOL_WAIT}초)..."
  local elapsed=0
  while (( elapsed < WOL_WAIT )); do
    if ssh -q -o ConnectTimeout=5 -o StrictHostKeyChecking=no \
         "${WIN_USER}@${WIN_IP}" -p ${WIN_SSH_PORT} "exit" 2>/dev/null; then
      ok "Windows PC SSH 응답 확인"
      return 0
    fi
    sleep 10
    (( elapsed += 10 ))
    log "대기 중... ${elapsed}/${WOL_WAIT}초"
  done
  err "Windows PC가 ${WOL_WAIT}초 내에 응답하지 않음"
  return 1
}

# ── 함수: Scheduled Task 등록 (최초 1회) ─────────────────────────────────────
setup_scheduled_task() {
  log "Windows Scheduled Task 등록 중: ${TASK_NAME}"

  # VM 시작 PowerShell 스크립트 내용 생성
  local ps_body=""
  for vm_name in "${!VMS[@]}"; do
    local vmx="${VMS[$vm_name]}"
    ps_body+="
    \$result = & '\$vmrun' -T ws list
    if (\$result -notmatch [regex]::Escape('\$vmx')) {
      Write-Host \"Starting ${vm_name}...\"
      & '\$vmrun' -T ws start '\$vmx' nogui
      Start-Sleep 3
    } else {
      Write-Host \"${vm_name} already running\"
    }"
  done

  # Windows에 Task 등록
  ssh -q -o StrictHostKeyChecking=no "${WIN_USER}@${WIN_IP}" -p ${WIN_SSH_PORT} "powershell -NonInteractive -Command \"
\$action = New-ScheduledTaskAction -Execute 'powershell.exe' \`
  -Argument '-NonInteractive -WindowStyle Hidden -Command \`\"
    \\\$vmrun = \\\"${VMRUN}\\\"
    ${ps_body}
  \`\"'
\$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddYears(10)
\$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit PT5M
\$principal = New-ScheduledTaskPrincipal -UserId \\\"\$env:USERNAME\\\" -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName '${TASK_NAME}' -Action \\\$action -Trigger \\\$trigger \`
  -Settings \\\$settings -Principal \\\$principal -Force
Write-Host 'Task registered: ${TASK_NAME}'
\""
  ok "Scheduled Task 등록 완료"
  echo ""
  warn "다음 단계: Windows에 로그인된 상태에서 한 번 작동 확인 권장"
  echo "  → schtasks /run /tn ${TASK_NAME}"
}

# ── 함수: VM 시작 (Scheduled Task 경유) ──────────────────────────────────────
start_vms_via_task() {
  log "Scheduled Task 실행 → ${TASK_NAME}"
  if $DRY_RUN; then
    warn "[dry-run] schtasks /run /tn ${TASK_NAME}"
    return
  fi

  ssh -q -o StrictHostKeyChecking=no "${WIN_USER}@${WIN_IP}" -p ${WIN_SSH_PORT} \
    "schtasks /run /tn ${TASK_NAME}" 2>&1 | while IFS= read -r line; do
    log "  Windows: $line"
  done

  log "VM 기동 대기 (30초)..."
  sleep 30
}

# ── 함수: VM 시작 (vm-control.ps1 직접 시도 - 폴백) ─────────────────────────
# Why: vmrun 비대화형 SSH 컨텍스트 문제 → vm-control.ps1이 경로/권한 처리
#      vm_mcp_server.py와 동일한 방식으로 통일
start_vms_direct() {
  log "vm-control.ps1 직접 실행 시도..."
  if $DRY_RUN; then
    for vm_name in worker1 worker2 worker3 worker4; do
      warn "[dry-run] powershell -File ${VM_SCRIPT} start ${vm_name}"
    done
    return
  fi

  for vm_name in worker1 worker2 worker3 worker4; do
    log "  ${vm_name} 시작 중..."
    ssh -q -o StrictHostKeyChecking=no "${WIN_USER}@${WIN_IP}" -p ${WIN_SSH_PORT} \
      "powershell -File \"${VM_SCRIPT}\" start ${vm_name} 2>&1" || \
      warn "  ${vm_name} 시작 실패 (이미 실행 중이거나 스크립트 오류)"
    sleep 2
  done
}

# ── 함수: 실행 중인 VM 목록 확인 ────────────────────────────────────────────
check_running_vms() {
  log "실행 중인 VM 목록 확인..."
  ssh -q -o StrictHostKeyChecking=no "${WIN_USER}@${WIN_IP}" -p ${WIN_SSH_PORT} \
    "powershell -File \"${VM_SCRIPT}\" list all 2>&1" | while IFS= read -r line; do
    log "  $line"
  done
}

# ── 함수: K8s 노드 Ready 대기 ────────────────────────────────────────────────
wait_for_nodes() {
  log "K8s 노드 Ready 대기 중 (최대 ${NODE_READY_WAIT}초)..."
  local elapsed=0
  local target_nodes=("k8s-worker1" "k8s-worker2" "k8s-worker3" "k8s-worker4")

  while (( elapsed < NODE_READY_WAIT )); do
    local all_ready=true
    local status_output

    status_output=$(kubectl get nodes --no-headers 2>/dev/null || echo "")

    echo ""
    log "노드 상태 (${elapsed}초 경과):"
    echo "$status_output" | while IFS= read -r line; do
      if echo "$line" | grep -q "Ready"; then
        echo -e "  ${GREEN}$line${NC}"
      else
        echo -e "  ${RED}$line${NC}"
      fi
    done

    for node in "${target_nodes[@]}"; do
      if ! echo "$status_output" | grep -q "${node}.*Ready" || \
           echo "$status_output" | grep -q "${node}.*NotReady"; then
        all_ready=false
        break
      fi
    done

    if $all_ready; then
      echo ""
      ok "모든 워커 노드 Ready 확인 ✅"
      return 0
    fi

    sleep $NODE_CHECK_INTERVAL
    (( elapsed += NODE_CHECK_INTERVAL ))
  done

  warn "일부 노드가 ${NODE_READY_WAIT}초 내에 Ready 상태가 되지 않음"
  kubectl get nodes
  return 1
}

# ══════════════════════════════════════════════════════════════════════════════
# 메인 실행
# ══════════════════════════════════════════════════════════════════════════════

echo ""
echo -e "${BLUE}════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  K8s 워커 노드 기동 스크립트${NC}"
echo -e "${BLUE}════════════════════════════════════════════════${NC}"
echo ""

# --setup 모드: Scheduled Task 등록 후 종료
if $SETUP; then
  wait_for_windows || exit 1
  setup_scheduled_task
  exit 0
fi

# Step 1: WOL
if $SKIP_WOL; then
  log "WOL 생략 (--skip-wol)"
else
  send_wol
  log "Windows PC 부팅 대기 중..."
  sleep 20  # 초기 부팅 대기
fi

# Step 2: SSH 응답 확인
if ! $DRY_RUN; then
  wait_for_windows || exit 1
fi

# Step 3: VM 시작
# 먼저 Scheduled Task 시도, 실패하면 vmrun 직접 시도
log "VM 기동 방식 결정..."
if ssh -q -o StrictHostKeyChecking=no "${WIN_USER}@${WIN_IP}" -p ${WIN_SSH_PORT} \
     "schtasks /query /tn ${TASK_NAME} 2>&1" | grep -q "${TASK_NAME}" 2>/dev/null; then
  log "Scheduled Task 방식으로 VM 시작"
  start_vms_via_task
else
  warn "Scheduled Task 미등록 → vmrun 직접 시도"
  warn "(안정적 사용을 위해 './start-workers.sh --setup' 실행 권장 — vm-control.ps1 폴백 사용 중)"
  start_vms_direct
fi

# Step 4: 실행 중인 VM 확인
if ! $DRY_RUN; then
  sleep 5
  check_running_vms
fi

# Step 5: K8s 노드 Ready 대기
echo ""
if ! $DRY_RUN; then
  wait_for_nodes
else
  warn "[dry-run] kubectl get nodes --watch 생략"
fi

echo ""
log "완료. kubectl get nodes:"
kubectl get nodes -o wide 2>/dev/null || true
echo ""
