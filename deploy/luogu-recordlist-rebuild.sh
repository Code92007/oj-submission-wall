#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SERVICE="${SERVICE:-oj-submission-wall}"
LOG_DIR="${LOG_DIR:-data/logs}"
PID_FILE="${PID_FILE:-data/luogu-recordlist-rebuild.pid}"
LOCK_FILE="${LOCK_FILE:-data/luogu-recordlist-rebuild.lock}"
LOG_FILE="${LOG_FILE:-$LOG_DIR/luogu-recordlist-rebuild.$(date +%Y%m%d-%H%M%S).log}"

# Backfill speed controls. Defaults are intentionally conservative.
HANDLE_IDS="${HANDLE_IDS:-}"              # Optional: "42 43". Empty means all active Luogu handles.
RESET_STATE="${RESET_STATE:-1}"          # Reset recordSync cursors so every record/list page is revisited.
CLEAN_SYNTHETIC="${CLEAN_SYNTHETIC:-1}"  # Delete old profile-derived luogu-activity rows.
PRIME_RECENT_PAGES="${PRIME_RECENT_PAGES:-1}"
PRIME_PAGES_PER_ROUND="${PRIME_PAGES_PER_ROUND:-1}"
PAGES_PER_ROUND="${PAGES_PER_ROUND:-2}"
RECENT_PAGES="${RECENT_PAGES:-0}"
SLEEP_MIN="${SLEEP_MIN:-8}"
SLEEP_MAX="${SLEEP_MAX:-20}"
ROUND_SLEEP="${ROUND_SLEEP:-45}"
MAX_ROUNDS="${MAX_ROUNDS:-0}"             # 0 means continue until each handle is complete or errors.
HANDLE_SLEEP_MIN="${HANDLE_SLEEP_MIN:-60}"
HANDLE_SLEEP_MAX="${HANDLE_SLEEP_MAX:-150}"
ALLOW_APP_SYNC_DURING_REBUILD="${ALLOW_APP_SYNC_DURING_REBUILD:-0}"

usage() {
  cat <<'EOF'
Usage:
  deploy/luogu-recordlist-rebuild.sh --background
  deploy/luogu-recordlist-rebuild.sh --foreground
  deploy/luogu-recordlist-rebuild.sh --status
  deploy/luogu-recordlist-rebuild.sh --stop

Optional env:
  HANDLE_IDS="42 43"           Only rebuild selected Luogu handle ids.
  PAGES_PER_ROUND=2            Historical record/list pages per round.
  SLEEP_MIN=8 SLEEP_MAX=20     Sleep seconds between Luogu page requests.
  ROUND_SLEEP=45               Sleep seconds between rounds for the same handle.
  MAX_ROUNDS=0                 0 means run until complete/error.
  RESET_STATE=1                Reset recordSync cursor before rebuilding.
  CLEAN_SYNTHETIC=1            Delete old profile-derived luogu-activity rows.
  ALLOW_APP_SYNC_DURING_REBUILD=1
                               Bypass the SYNC_INTERVAL_SECONDS=0 safety check.
EOF
}

compose_exec() {
  docker compose exec -T "$SERVICE" "$@"
}

random_sleep() {
  local min="$1"
  local max="$2"
  if (( max <= min )); then
    sleep "$min"
    return
  fi
  sleep $(( min + RANDOM % (max - min + 1) ))
}

status() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "running pid=$pid"
    else
      echo "pid file exists but process is not running: $pid"
    fi
  else
    echo "not running"
  fi
  echo
  echo "latest logs:"
  ls -1t "$LOG_DIR"/luogu-recordlist-rebuild.*.log 2>/dev/null | head -3 || true
  echo
  compose_exec python - <<'PY'
import json
import app

app.init_db()
with app.connect_db() as conn:
    rows = conn.execute("""
        SELECT id, handle, last_sync_at, last_error, stats_json
        FROM handles
        WHERE platform = 'luogu' AND active = 1
        ORDER BY id
    """).fetchall()
    for row in rows:
        stats = json.loads(row["stats_json"] or "{}") if row["stats_json"] else {}
        rs = stats.get("recordSync") if isinstance(stats.get("recordSync"), dict) else {}
        print(
            f"id={row['id']} handle={row['handle']} "
            f"next={rs.get('nextBackfillPage')} pages={rs.get('pageCount')} "
            f"complete={bool(rs.get('historyComplete'))} "
            f"lastError={(row['last_error'] or rs.get('lastError') or '')[:100]}"
        )
PY
}

stop_job() {
  if [[ ! -f "$PID_FILE" ]]; then
    echo "no pid file"
    return 0
  fi
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    echo "process is not running: $pid"
    rm -f "$PID_FILE"
    return 0
  fi
  kill "$pid"
  echo "sent SIGTERM to pid=$pid"
}

prepare_database() {
  echo "preparing database: backup, cleanup, reset cursors"
  docker compose exec -T \
    -e HANDLE_IDS="$HANDLE_IDS" \
    -e RESET_STATE="$RESET_STATE" \
    -e CLEAN_SYNTHETIC="$CLEAN_SYNTHETIC" \
    "$SERVICE" python - <<'PY'
import datetime as dt
import json
import os
import sqlite3

import app

selected_ids = [int(item) for item in os.environ.get("HANDLE_IDS", "").split() if item.strip()]
reset_state = os.environ.get("RESET_STATE", "1").lower() not in {"0", "false", "no", "off"}
clean_synthetic = os.environ.get("CLEAN_SYNTHETIC", "1").lower() not in {"0", "false", "no", "off"}

app.init_db()
backup_dir = app.DATA_DIR / "backups"
backup_dir.mkdir(parents=True, exist_ok=True)
stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
backup_path = backup_dir / f"ojwall.sqlite3.before-luogu-recordlist-{stamp}.bak"

with sqlite3.connect(app.DB_PATH) as source, sqlite3.connect(backup_path) as dest:
    source.backup(dest)

with app.connect_db() as conn:
    params = []
    where = "platform = 'luogu' AND active = 1"
    if selected_ids:
        where += " AND id IN (%s)" % ",".join("?" for _ in selected_ids)
        params.extend(selected_ids)
    handles = conn.execute(f"SELECT * FROM handles WHERE {where} ORDER BY id", params).fetchall()
    if not handles:
        raise SystemExit("no active Luogu handles matched")

    total_deleted = 0
    for row in handles:
        if clean_synthetic:
            cur = conn.execute(
                """
                DELETE FROM submissions
                WHERE owner_type = ?
                  AND owner_id = ?
                  AND platform = 'luogu'
                  AND handle = ?
                  AND (
                    problem_id LIKE 'luogu-activity-%'
                    OR remote_id LIKE 'profile-%'
                    OR raw_json LIKE '%syntheticFromProfile%'
                  )
                """,
                (row["owner_type"], row["owner_id"], row["handle"]),
            )
            total_deleted += cur.rowcount

        if reset_state:
            stats = {}
            if row["stats_json"]:
                try:
                    parsed = json.loads(row["stats_json"])
                    if isinstance(parsed, dict):
                        stats = parsed
                except json.JSONDecodeError:
                    stats = {}
            stats.pop("recordSync", None)
            if stats.get("source") == "luogu-profile+record-list":
                stats["source"] = "luogu-profile"
            stats_json = json.dumps(stats, ensure_ascii=False) if stats else None
            conn.execute(
                "UPDATE handles SET last_error = NULL, stats_json = ? WHERE id = ?",
                (stats_json, row["id"]),
            )
    conn.commit()

    print(f"backup={backup_path}")
    print(f"handles={','.join(str(row['id']) for row in handles)}")
    print(f"deleted_synthetic_rows={total_deleted}")
PY
}

handle_ids() {
  docker compose exec -T -e HANDLE_IDS="$HANDLE_IDS" "$SERVICE" python - <<'PY'
import os
import app

selected = [int(item) for item in os.environ.get("HANDLE_IDS", "").split() if item.strip()]
app.init_db()
with app.connect_db() as conn:
    params = []
    where = "platform = 'luogu' AND active = 1"
    if selected:
        where += " AND id IN (%s)" % ",".join("?" for _ in selected)
        params.extend(selected)
    for row in conn.execute(f"SELECT id FROM handles WHERE {where} ORDER BY id", params):
        print(row["id"])
PY
}

preflight() {
  echo "preflight"
  docker compose exec -T \
    -e ALLOW_APP_SYNC_DURING_REBUILD="$ALLOW_APP_SYNC_DURING_REBUILD" \
    "$SERVICE" python - <<'PY'
import os

cookie = os.environ.get("LUOGU_COOKIE", "")
keys = [part.split("=", 1)[0].strip() for part in cookie.split(";") if "=" in part]
print("proxy_url_set:", bool(os.environ.get("LUOGU_PROXY_URL")))
print("proxy_token_set:", bool(os.environ.get("LUOGU_PROXY_TOKEN")))
print("cookie_len:", len(cookie))
print("cookie_keys:", keys)
print("csrf_set:", bool(os.environ.get("LUOGU_CSRF_TOKEN")))
print("sync_interval_seconds:", os.environ.get("SYNC_INTERVAL_SECONDS", ""))
if not os.environ.get("LUOGU_PROXY_URL") or not os.environ.get("LUOGU_PROXY_TOKEN"):
    raise SystemExit("LUOGU_PROXY_URL/LUOGU_PROXY_TOKEN is required")
if not cookie:
    raise SystemExit("LUOGU_COOKIE is empty in container")
if os.environ.get("SYNC_INTERVAL_SECONDS", "") not in {"", "0"} and os.environ.get("ALLOW_APP_SYNC_DURING_REBUILD") != "1":
    raise SystemExit("set SYNC_INTERVAL_SECONDS=0 and recreate the app before running this rebuild")
PY
}

foreground() {
  mkdir -p "$LOG_DIR" data
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "another rebuild is already running"
    exit 1
  fi

  echo "started_at=$(date -Is)"
  echo "service=$SERVICE"
  echo "handle_ids=${HANDLE_IDS:-all}"
  echo "pages_per_round=$PAGES_PER_ROUND recent_pages=$RECENT_PAGES sleep=$SLEEP_MIN-$SLEEP_MAX round_sleep=$ROUND_SLEEP max_rounds=$MAX_ROUNDS"

  preflight
  prepare_database

  mapfile -t ids < <(handle_ids)
  if (( ${#ids[@]} == 0 )); then
    echo "no handles to rebuild"
    exit 0
  fi

  echo "prime page 1 for each handle"
  for id in "${ids[@]}"; do
    echo "== prime handle $id =="
    compose_exec python app.py luogu-backfill \
      --handle-id "$id" \
      --recent-pages "$PRIME_RECENT_PAGES" \
      --pages-per-round "$PRIME_PAGES_PER_ROUND" \
      --sleep-min "$SLEEP_MIN" \
      --sleep-max "$SLEEP_MAX" \
      --round-sleep "$ROUND_SLEEP" \
      --max-rounds 1
    random_sleep "$HANDLE_SLEEP_MIN" "$HANDLE_SLEEP_MAX"
  done

  handle_args=()
  for id in "${ids[@]}"; do
    handle_args+=(--handle-id "$id")
  done

  echo "historical backfill"
  compose_exec python app.py luogu-backfill \
    "${handle_args[@]}" \
    --recent-pages "$RECENT_PAGES" \
    --pages-per-round "$PAGES_PER_ROUND" \
    --sleep-min "$SLEEP_MIN" \
    --sleep-max "$SLEEP_MAX" \
    --round-sleep "$ROUND_SLEEP" \
    --max-rounds "$MAX_ROUNDS"

  echo "finished_at=$(date -Is)"
  status
}

case "${1:-}" in
  --background)
    mkdir -p "$LOG_DIR" data
    if [[ -f "$PID_FILE" ]]; then
      old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
      if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
        echo "already running pid=$old_pid"
        exit 1
      fi
    fi
    nohup "$0" --foreground >"$LOG_FILE" 2>&1 &
    echo "$!" >"$PID_FILE"
    echo "submitted pid=$(cat "$PID_FILE")"
    echo "log=$LOG_FILE"
    ;;
  --foreground|"")
    foreground
    ;;
  --status)
    status
    ;;
  --stop)
    stop_job
    ;;
  -h|--help)
    usage
    ;;
  *)
    usage
    exit 2
    ;;
esac
