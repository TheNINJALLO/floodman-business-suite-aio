#!/bin/sh
set -eu

FM_HOME="${FM_HOME:-/home/container}"
FM_CONFIG="${FM_CONFIG:-$FM_HOME/config}"
FM_DATA="${FM_DATA:-$FM_HOME/data}"
FM_RUN="${FM_RUN:-$FM_HOME/run}"
FM_LOGS="${FM_LOGS:-$FM_HOME/logs}"

fm_log() {
  printf '[Floodman] %s\n' "$*"
}

fm_warn() {
  printf '[Floodman][WARN] %s\n' "$*" >&2
}

fm_die() {
  printf '[Floodman][ERROR] %s\n' "$*" >&2
  exit 1
}

fm_wait_tcp() {
  host="$1"; port="$2"; timeout="${3:-300}"
  start="$(date +%s)"
  while ! nc -z "$host" "$port" >/dev/null 2>&1; do
    now="$(date +%s)"
    [ $((now - start)) -lt "$timeout" ] || return 1
    sleep 2
  done
}

fm_wait_http() {
  url="$1"; timeout="${2:-300}"; allow_http_error="${3:-false}"
  start="$(date +%s)"
  while :; do
    code="$(curl -ksS -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null || true)"
    case "$code" in
      2??|3??) return 0 ;;
      4??) [ "$allow_http_error" = "true" ] && return 0 ;;
    esac
    now="$(date +%s)"
    [ $((now - start)) -lt "$timeout" ] || return 1
    sleep 3
  done
}

fm_shell_quote() {
  # POSIX-safe single-quote escaping. The output can be sourced by /bin/sh.
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\"'\"'/g")"
}

fm_env_set() {
  file="$1"; key="$2"; value="$3"
  printf '%s=%s\n' "$key" "$(fm_shell_quote "$value")" >> "$file"
}
