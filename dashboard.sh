#!/bin/bash
# dashboard.sh — Terminal monitoring dashboard for the backend VM
# Usage: bash dashboard.sh              (single snapshot)
#        bash dashboard.sh --live       (auto-refresh every 5s)
#        bash dashboard.sh --live --interval 10

set -uo pipefail

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# Auto-disable colors when piped
if [[ ! -t 1 ]]; then
    RED='' GREEN='' YELLOW='' CYAN='' BOLD='' DIM='' NC=''
fi

# --- Config ---
DOCKER_IMAGE="firestorm-contact-us-backend"
LIVE=false
INTERVAL=5

# --- Args ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --live)      LIVE=true; shift ;;
        --interval)  INTERVAL="$2"; shift 2 ;;
        --no-color)  RED='' GREEN='' YELLOW='' CYAN='' BOLD='' DIM='' NC=''; shift ;;
        --help)
            echo "Usage: bash dashboard.sh [--live] [--interval N] [--no-color]"
            exit 0
            ;;
        *)  echo "Unknown option: $1"; exit 1 ;;
    esac
done

# --- Find the backend container ---
find_container() {
    sudo docker ps --filter "ancestor=$DOCKER_IMAGE" --format "{{.ID}}" 2>/dev/null | head -1
}

# === SECTIONS ===

print_header() {
    printf "${CYAN}======================================================================${NC}\n"
    printf "${BOLD}  BACKEND DASHBOARD  ${NC}${DIM}%s${NC}\n" "$(date '+%Y-%m-%d %H:%M:%S %Z')"
    printf "${CYAN}======================================================================${NC}\n"
}

print_system() {
    printf "\n${BOLD}[ SYSTEM ]${NC}\n"
    printf "  Hostname : %s\n" "$(hostname)"
    printf "  Uptime   : %s\n" "$(uptime -p 2>/dev/null || uptime | sed 's/.*up /up /' | sed 's/,.*load.*//')"
    printf "  OS       : %s\n" "$(grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '"' || echo 'unknown')"
    printf "  Kernel   : %s\n" "$(uname -r)"
}

print_resources() {
    printf "\n${BOLD}[ RESOURCES ]${NC}\n"

    local load cores
    load=$(awk '{print $1, $2, $3}' /proc/loadavg 2>/dev/null || echo "n/a")
    cores=$(nproc 2>/dev/null || echo "?")
    printf "  CPU Load : %s  (%s cores)\n" "$load" "$cores"

    local mem_info
    mem_info=$(free -m 2>/dev/null | awk '/^Mem:/ {printf "%dMB / %dMB (%.0f%%)", $3, $2, ($2>0 ? $3/$2*100 : 0)}')
    printf "  Memory   : %s\n" "${mem_info:-n/a}"

    local swap_info
    swap_info=$(free -m 2>/dev/null | awk '/^Swap:/ {if ($2>0) printf "%dMB / %dMB (%.0f%%)", $3, $2, $3/$2*100; else print "disabled"}')
    printf "  Swap     : %s\n" "${swap_info:-n/a}"

    local disk_info
    disk_info=$(df -h / 2>/dev/null | awk 'NR==2 {printf "%s / %s (%s)", $3, $2, $5}')
    printf "  Disk /   : %s\n" "${disk_info:-n/a}"
}

print_docker() {
    local cid="$1"
    printf "\n${BOLD}[ DOCKER CONTAINER ]${NC}\n"

    if [[ -z "$cid" ]]; then
        printf "  ${RED}NO CONTAINER RUNNING${NC} (image: %s)\n" "$DOCKER_IMAGE"
        # Check if container exists but is stopped
        local stopped
        stopped=$(sudo docker ps -a --filter "ancestor=$DOCKER_IMAGE" --filter "status=exited" --format "{{.ID}} {{.Status}}" 2>/dev/null | head -1)
        if [[ -n "$stopped" ]]; then
            printf "  ${YELLOW}Stopped container found: %s${NC}\n" "$stopped"
        fi
        return
    fi

    local name status ports running_for
    name=$(sudo docker inspect --format='{{.Name}}' "$cid" 2>/dev/null | sed 's|^/||')
    status=$(sudo docker inspect --format='{{.State.Status}}' "$cid" 2>/dev/null)
    ports=$(sudo docker port "$cid" 2>/dev/null | tr '\n' ', ' | sed 's/, $//')
    running_for=$(sudo docker ps --filter "id=$cid" --format "{{.RunningFor}}" 2>/dev/null)

    local restart_count
    restart_count=$(sudo docker inspect --format='{{.RestartCount}}' "$cid" 2>/dev/null || echo "0")

    printf "  Name     : ${GREEN}%s${NC}\n" "${name:-unnamed}"
    printf "  ID       : %s\n" "$cid"
    printf "  Status   : ${GREEN}%s${NC}\n" "${status:-unknown}"
    printf "  Uptime   : %s\n" "${running_for:-unknown}"
    printf "  Ports    : %s\n" "${ports:-none mapped}"
    printf "  Restarts : %s\n" "${restart_count}"
    printf "  Image    : %s\n" "$DOCKER_IMAGE"
}

check_container_service() {
    local cid="$1" name="$2" pattern="$3"

    if sudo docker exec "$cid" pgrep -f "$pattern" > /dev/null 2>&1; then
        local pids
        pids=$(sudo docker exec "$cid" pgrep -f "$pattern" 2>/dev/null | head -3 | tr '\n' ' ')
        printf "  ${GREEN}%-15s RUNNING${NC}  PIDs: %s\n" "$name" "$pids"
    else
        printf "  ${RED}%-15s DOWN${NC}\n" "$name"
    fi
}

print_services() {
    local cid="$1"
    printf "\n${BOLD}[ SERVICES IN CONTAINER ]${NC}\n"

    if [[ -z "$cid" ]]; then
        printf "  ${DIM}(skipped — no running container)${NC}\n"
        return
    fi

    check_container_service "$cid" "uvicorn"       "uvicorn.*app.main:app"
    check_container_service "$cid" "redis"          "redis-server"
    check_container_service "$cid" "celery-worker"  "celery.*worker"
    check_container_service "$cid" "celery-beat"    "celery.*beat"
}

print_mysql() {
    printf "\n${BOLD}[ MYSQL (HOST) ]${NC}\n"

    # Check if mysql service is running
    if systemctl is-active mysql > /dev/null 2>&1 || systemctl is-active mysqld > /dev/null 2>&1; then
        printf "  Service  : ${GREEN}RUNNING${NC}\n"
    elif pgrep -x mysqld > /dev/null 2>&1; then
        printf "  Service  : ${GREEN}RUNNING${NC} (process found)\n"
    else
        printf "  Service  : ${RED}DOWN${NC}\n"
    fi

    # Port check
    if ss -tlnp 2>/dev/null | grep -q ":3306 "; then
        printf "  Port 3306: ${GREEN}OPEN${NC}\n"
    else
        printf "  Port 3306: ${RED}CLOSED${NC}\n"
    fi

    # Ping test
    if command -v mysqladmin > /dev/null 2>&1; then
        if mysqladmin ping 2>/dev/null | grep -q "alive"; then
            printf "  Ping     : ${GREEN}alive${NC}\n"
        else
            printf "  Ping     : ${RED}not responding${NC}\n"
        fi
    fi
}

print_ports() {
    printf "\n${BOLD}[ LISTENING PORTS ]${NC}\n"
    ss -tlnp 2>/dev/null | awk 'NR>1 {
        split($4, a, ":")
        port = a[length(a)]
        addr = $4
        proc = $6
        gsub(/.*"/, "", proc); gsub(/".*/, "", proc)
        printf "  %-25s %s\n", addr, proc
    }' | sort -t: -k2 -n | head -15
}

print_logs() {
    local cid="$1"
    printf "\n${BOLD}[ RECENT ERRORS ]${NC}\n"

    # Docker container logs
    printf "  ${DIM}--- Container (docker logs) ---${NC}\n"
    if [[ -n "$cid" ]]; then
        local errors
        errors=$(sudo docker logs --tail 100 "$cid" 2>&1 | grep -iE '(error|exception|traceback|critical|fatal|refused|timeout)' | tail -5)
        if [[ -n "$errors" ]]; then
            while IFS= read -r line; do
                printf "    ${RED}%s${NC}\n" "${line:0:120}"
            done <<< "$errors"
        else
            printf "    ${GREEN}(no errors in last 100 lines)${NC}\n"
        fi
    else
        printf "    ${DIM}(no container to read logs from)${NC}\n"
    fi

    # MySQL error log
    printf "  ${DIM}--- MySQL ---${NC}\n"
    local mysql_log=""
    for f in /var/log/mysql/error.log /var/log/mysqld.log /var/log/mysql.err; do
        if [[ -f "$f" ]]; then
            mysql_log="$f"
            break
        fi
    done
    if [[ -n "$mysql_log" ]]; then
        local merr
        merr=$(tail -50 "$mysql_log" 2>/dev/null | grep -iE '(error|warning|fatal)' | tail -3)
        if [[ -n "$merr" ]]; then
            while IFS= read -r line; do
                printf "    ${YELLOW}%s${NC}\n" "${line:0:120}"
            done <<< "$merr"
        else
            printf "    ${GREEN}(no errors)${NC}\n"
        fi
    else
        printf "    ${DIM}(no mysql error log found)${NC}\n"
    fi
}

print_health() {
    printf "\n${BOLD}[ HEALTH CHECK ]${NC}\n"

    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:8080/health 2>/dev/null)

    if [[ "$code" == "200" ]]; then
        local body
        body=$(curl -s --max-time 3 http://localhost:8080/health 2>/dev/null)
        printf "  GET /health : ${GREEN}%s${NC} — %s\n" "$code" "$body"
    elif [[ "$code" == "000" ]]; then
        printf "  GET /health : ${RED}UNREACHABLE${NC} (connection refused or timeout)\n"
    else
        printf "  GET /health : ${YELLOW}%s${NC}\n" "$code"
    fi
}

print_ext_ip() {
    printf "\n${BOLD}[ EXTERNAL IP ]${NC}\n"
    local ip
    ip=$(curl -s --max-time 3 https://ifconfig.me 2>/dev/null || echo "unavailable")
    printf "  %s\n" "$ip"
}

# === RENDER ===

render_dashboard() {
    local cid
    cid=$(find_container)

    print_header
    print_system
    print_resources
    print_docker "$cid"
    print_services "$cid"
    print_mysql
    print_ports
    print_logs "$cid"
    print_health
    print_ext_ip
    printf "\n${DIM}----------------------------------------------------------------------${NC}\n"
}

# === MAIN ===

if [[ "$LIVE" == true ]]; then
    trap 'printf "\n${NC}Dashboard stopped.\n"; exit 0' INT TERM
    while true; do
        clear
        render_dashboard
        printf "${DIM}Refreshing every %ss. Ctrl+C to stop.${NC}\n" "$INTERVAL"
        sleep "$INTERVAL"
    done
else
    render_dashboard
fi
