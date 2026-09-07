#!/usr/bin/env bash
set -uo pipefail

REPO=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$REPO" || exit 1

JOBS=${JOBS:-$( (nproc 2>/dev/null || echo 4) )}
PORT=${PORT:-}
ARTIFACTS=${ARTIFACTS:-}
ASSUME_YES=0
QUIET=0
ACTION=""
LOGDIR=${LOGDIR:-$(dirname "$REPO")}
BOARD_ID_HINT="usb-1a86"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
warn()  { printf '  ! %s\n' "$*" >&2; }
info()  { printf '  %s\n' "$*"; }
die()   { red "error: $*"; exit 1; }

read_reply() {
	if { : < /dev/tty; } 2>/dev/null; then
		read -r "$1" < /dev/tty
	else
		read -r "$1"
	fi
}

ask() {
	[ "$ASSUME_YES" = 1 ] && return 0
	local reply=""
	printf '%s [y/N] ' "$1"
	read_reply reply || return 1
	case "$reply" in [yY]*) return 0 ;; *) return 1 ;; esac
}

usage() {
	cat <<'EOF'
Usage: ./run.sh [options] [action]

With no action it opens the interactive menu.

Actions:
  --check        Check the environment and fix what can be fixed
  --build        Build everything from clean sources
  --verify       Check the checksums of a build
  --flash        Write the image to the board (ERASES /etc and /home)
  --test         Run the board test suite
  --all          check, build, verify, flash and test, in that order
  --repro        Two builds of the same commit and a comparison
  --recover      Put the board's /etc and /home back to factory
  --status       Show existing builds and the state of the board

Options:
  -y, --yes            Do not prompt; assume yes
  -q, --quiet          Send build output to the log only, not to the screen
  -j, --jobs N         Parallel build jobs (default: nproc)
  -p, --port PATH      Serial adapter (default: autodetect)
  -a, --artifacts DIR  Artifacts directory to use
  -h, --help           This help
EOF
}

have() { command -v "$1" >/dev/null 2>&1; }

python_with_pyserial() {
	local candidate
	for candidate in \
		"${PYSERIAL_PYTHON:-}" \
		python3 \
		"$HOME/.local/share/pipx/venvs/esptool/bin/python3" \
		/usr/bin/python3
	do
		[ -n "$candidate" ] || continue
		have "$candidate" || [ -x "$candidate" ] || continue
		if "$candidate" -c 'import serial' >/dev/null 2>&1; then
			printf '%s\n' "$candidate"
			return 0
		fi
	done
	return 1
}

disk_free_gb() { df -PBG "$REPO" 2>/dev/null | awk 'NR==2 {gsub("G","",$4); print $4}'; }

detect_port() {
	local p
	if [ -n "$PORT" ]; then printf '%s\n' "$PORT"; return 0; fi
	for p in /dev/serial/by-id/*"$BOARD_ID_HINT"*; do
		[ -e "$p" ] && { printf '%s\n' "$p"; return 0; }
	done
	for p in /dev/serial/by-id/*; do
		[ -e "$p" ] && { printf '%s\n' "$p"; return 0; }
	done
	for p in /dev/ttyACM0 /dev/ttyACM1 /dev/ttyUSB0 /dev/ttyUSB1; do
		[ -e "$p" ] && { printf '%s\n' "$p"; return 0; }
	done
	return 1
}

port_holders() {
	local target
	target=$(readlink -f "$1" 2>/dev/null || printf '%s' "$1")
	fuser "$target" 2>/dev/null | tr -s ' ' '\n' | grep -E '^[0-9]+$' || true
}

free_port() {
	local port pids pid
	port=$1
	pids=$(port_holders "$port")
	[ -z "$pids" ] && return 0
	warn "the port is held by:"
	for pid in $pids; do
		info "  pid $pid  $(ps -o args= -p "$pid" 2>/dev/null | cut -c1-70)"
	done
	warn "an open console steals bytes and also resets the board when it opens"
	if ask "  Close those processes?"; then
		for pid in $pids; do kill "$pid" 2>/dev/null; done
		sleep 1
		for pid in $(port_holders "$port"); do kill -9 "$pid" 2>/dev/null; done
		sleep 1
		[ -z "$(port_holders "$port")" ] && { green "  port released"; return 0; }
		warn "could not release it"
		return 1
	fi
	return 1
}

builds() { ls -dt "$REPO"/build-output/reproduce.*/artifacts 2>/dev/null; }

latest_artifacts() {
	if [ -n "$ARTIFACTS" ]; then printf '%s\n' "$ARTIFACTS"; return 0; fi
	local first
	first=$(builds | head -1)
	[ -n "$first" ] && { printf '%s\n' "$first"; return 0; }
	return 1
}

clean_tree_or_fix() {
	local dirty stray f
	dirty=$(git -C "$REPO" status --porcelain 2>/dev/null)
	[ -z "$dirty" ] && return 0
	warn "the tree is not clean and reproduce.sh snapshots HEAD:"
	printf '%s\n' "$dirty" | sed 's/^/      /'
	stray=$(printf '%s\n' "$dirty" | awk '$1=="??" && $2 ~ /\.log$/ {print $2}')
	if [ -n "$stray" ]; then
		if ask "  Move the stray .log files out of the repository?"; then
			for f in $stray; do
				mv "$REPO/$f" "$LOGDIR/" 2>/dev/null && info "moved: $f -> $LOGDIR/"
			done
		fi
	fi
	dirty=$(git -C "$REPO" status --porcelain 2>/dev/null)
	[ -z "$dirty" ] && { green "  tree is clean"; return 0; }
	warn "there are uncommitted changes; commit or stash them before building"
	return 1
}

check_env() {
	bold "== Environment =="
	local problems=0 py free port

	for c in git docker python3 sha256sum awk; do
		if have "$c"; then info "ok       $c"; else red "  missing  $c"; problems=$((problems+1)); fi
	done

	if docker info >/dev/null 2>&1; then
		info "ok       docker responds"
	else
		red "  problem  docker does not respond (service stopped or missing group permission)"
		info "         try: systemctl --user start docker  |  sudo usermod -aG docker \$USER"
		problems=$((problems+1))
	fi

	if have esptool || have esptool.py; then
		info "ok       esptool"
	else
		red "  missing  esptool"
		info "         install with: pipx install esptool   (or pip install --user esptool)"
		problems=$((problems+1))
	fi

	if py=$(python_with_pyserial); then
		info "ok       pyserial on $py"
	else
		red "  missing  pyserial (the board test suite needs it)"
		info "         install with: pipx inject esptool pyserial   (or pip install --user pyserial)"
		problems=$((problems+1))
	fi

	free=$(disk_free_gb)
	if [ -n "$free" ] && [ "$free" -ge 25 ] 2>/dev/null; then
		info "ok       disk: ${free} GB free"
	else
		red "  problem  disk: ${free:-?} GB free; one build takes about 21 GB"
		problems=$((problems+1))
	fi

	if port=$(detect_port); then
		info "ok       board on $port"
		[ -n "$(port_holders "$port")" ] && warn "the port is busy (see the release option)"
	else
		warn "no serial adapter detected; connect the board to flash it"
	fi

	if [ -d "$REPO/.git" ]; then
		info "ok       commit $(git -C "$REPO" rev-parse --short HEAD 2>/dev/null) on $(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null)"
	fi

	echo
	if [ "$problems" -eq 0 ]; then green "No problems."; else red "$problems problem(s) to resolve."; fi
	return "$problems"
}

do_status() {
	bold "== Builds =="
	local a manifest
	if [ -z "$(builds)" ]; then
		info "none yet"
	else
		while IFS= read -r a; do
			manifest="$a/build-manifest.json"
			printf '  %s\n' "${a#$REPO/}"
			if [ -f "$manifest" ]; then
				python3 - "$manifest" <<'PY' 2>/dev/null || true
import json, sys
m = json.load(open(sys.argv[1]))
v = m.get('board_verification')
print('      commit', m.get('source_commit', '?')[:12],
      '| image', m.get('sha256', {}).get('linux-esp32s3-native-full.bin', '?')[:16],
      '| board', v if isinstance(v, str) else v.get('status', '?'))
PY
			fi
		done < <(builds)
	fi
	echo
	bold "== Board =="
	local port
	if port=$(detect_port); then
		info "port $port"
		local h; h=$(port_holders "$port")
		[ -n "$h" ] && warn "held by: $h" || info "free"
	else
		info "not detected"
	fi
}

do_build() {
	bold "== Build from clean sources =="
	have docker || die "docker is missing"
	docker info >/dev/null 2>&1 || die "docker does not respond"
	local free; free=$(disk_free_gb)
	if [ -n "$free" ] && [ "$free" -lt 25 ] 2>/dev/null; then
		warn "only ${free} GB free and the build takes about 21 GB"
		ask "  Continue anyway?" || return 1
	fi
	clean_tree_or_fix || return 1
	local log="$LOGDIR/esp32-build-$(date +%Y%m%d-%H%M%S).log"
	info "jobs:  $JOBS"
	info "log:   $log"
	echo
	bold "This downloads and compiles a cross toolchain, the kernel, the"
	bold "firmware and the userspace from source. It takes a long time:"
	bold "roughly 40 minutes on 8 jobs, longer on fewer, and it needs"
	bold "about 21 GB. The build output scrolls below as it happens."
	echo
	[ "$QUIET" = 1 ] && info "(quiet: output only goes to the log)"
	ask "  Start the build?" || { info "cancelled"; return 1; }
	echo
	local started rc elapsed
	started=$(date +%s)
	if [ "$QUIET" = 1 ]; then
		JOBS="$JOBS" bash "$REPO/build/reproduce.sh" > "$log" 2>&1
		rc=$?
	else
		JOBS="$JOBS" bash "$REPO/build/reproduce.sh" 2>&1 | tee "$log"
		rc=${PIPESTATUS[0]}
	fi
	elapsed=$(( $(date +%s) - started ))
	echo
	info "elapsed: $((elapsed / 60))m $((elapsed % 60))s"
	if [ "$rc" -ne 0 ]; then
		red "the build failed (code $rc)"
		info "last lines of $log:"
		tail -15 "$log" | sed 's/^/      /'
		return 1
	fi
	ARTIFACTS=$(builds | head -1)
	green "done: ${ARTIFACTS#$REPO/}"
}

do_verify() {
	bold "== Check checksums =="
	local a; a=$(latest_artifacts) || { red "no artifacts; build first"; return 1; }
	info "${a#$REPO/}"
	[ -f "$a/SHA256SUMS" ] || { red "SHA256SUMS is missing"; return 1; }
	if ( cd "$a" && sha256sum -c SHA256SUMS ) | sed 's/^/  /'; then
		green "every artifact matches"
		return 0
	fi
	red "some artifacts do not match their checksum"
	return 1
}

do_flash() {
	bold "== Flash =="
	local a port
	a=$(latest_artifacts) || { red "no artifacts; build first"; return 1; }
	port=$(detect_port) || { red "no board detected; pass -p PATH"; return 1; }
	info "image: ${a#$REPO/}"
	info "port:  $port"
	red   "this ERASES /etc and /home on the board"
	ask "  Write the image?" || { info "cancelled"; return 1; }
	free_port "$port" || { red "release the port and try again"; return 1; }
	"$REPO/flash.sh" -p "$port" --images "$a"
	local rc=$?
	[ "$rc" -eq 0 ] && green "flashing finished" || red "flashing failed (code $rc)"
	return "$rc"
}

do_test() {
	bold "== Board test suite =="
	local a port py out n
	a=$(latest_artifacts) || { red "no artifacts"; return 1; }
	port=$(detect_port) || { red "no board detected"; return 1; }
	py=$(python_with_pyserial) || { red "no python with pyserial"; info "install with: pipx inject esptool pyserial"; return 1; }
	free_port "$port" || return 1
	out="$REPO/build-output/board-check"
	n=2
	while [ -e "$out" ]; do out="$REPO/build-output/board-check-$n"; n=$((n+1)); done
	info "output: ${out#$REPO/}"
	info "26 tests, about 5 minutes"
	"$py" "$REPO/build/test-board.py" "$port" "$a" --output "$out" --reset-from-bootloader
	local rc=$?
	if [ -f "$out/results.json" ]; then
		python3 - "$out/results.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
bad = [t['name'] for t in r['tests'] if t['status'] != 'pass']
print(f"  {r['status'].upper()}: {len(r['tests'])} tests, {len(bad)} failed")
for name in bad:
    print('    failed:', name)
PY
	fi
	if [ "$rc" -ne 0 ]; then
		red "the suite did not pass"
		warn "if it was cut short, test users are left on the board;"
		warn "use the recover option before retrying"
		return 1
	fi
	green "every test passed"
}

do_recover() {
	bold "== Restore /etc and /home to factory =="
	local a port
	a=$(latest_artifacts) || { red "no artifacts to take the partitions from"; return 1; }
	port=$(detect_port) || { red "no board detected"; return 1; }
	for f in etc.jffs2 home.jffs2; do
		[ -f "$a/$f" ] || { red "$a/$f is missing"; return 1; }
	done
	red "this erases the current /etc and /home on the board"
	ask "  Continue?" || return 1
	free_port "$port" || return 1
	local tool; tool=$(have esptool && echo esptool || echo esptool.py)
	"$tool" --chip esp32s3 --port "$port" --baud 460800 \
		--before default-reset --after no-reset \
		write-flash 0xd0000 "$a/etc.jffs2" 0xcc0000 "$a/home.jffs2"
	local rc=$?
	[ "$rc" -eq 0 ] && green "partitions restored" || red "the restore failed"
	return "$rc"
}

do_repro() {
	bold "== Reproducibility: two builds of the same commit =="
	local first second
	first=$(builds | head -1)
	if [ -z "$first" ]; then
		info "no build yet; making the first one"
		do_build || return 1
		first=$(builds | head -1)
	else
		info "first: ${first#$REPO/}"
	fi
	info "now the second one, same commit"
	do_build || return 1
	second=$(builds | head -1)
	if [ "$second" = "$first" ]; then red "a second build did not appear"; return 1; fi
	bold "== Comparison =="
	python3 "$REPO/build/compare-builds.py" "${first%/artifacts}" "${second%/artifacts}"
}

do_all() {
	check_env || { ask "  There are problems. Continue anyway?" || return 1; }
	do_build   || return 1
	do_verify  || return 1
	do_flash   || return 1
	do_test    || return 1
	green "complete path finished"
}

menu() {
	while true; do
		echo
		bold "=== Linux on ESP32-S3 ==="
		cat <<'EOF'
  1) Check the environment
  2) Build everything from clean sources
  3) Check the checksums of a build
  4) Flash the board
  5) Run the board test suite
  6) EVERYTHING: build, check, flash and test
  7) Reproducibility: two builds and a comparison
  8) Recover the board (restore /etc and /home)
  9) Status
  0) Quit
EOF
		printf 'Choice: '
		local choice=""
		read_reply choice || { echo; return 0; }
		case "$choice" in
			1) check_env ;;
			2) do_build ;;
			3) do_verify ;;
			4) do_flash ;;
			5) do_test ;;
			6) do_all ;;
			7) do_repro ;;
			8) do_recover ;;
			9) do_status ;;
			0|q|Q) return 0 ;;
			*) warn "invalid choice" ;;
		esac
	done
}

while [ $# -gt 0 ]; do
	case "$1" in
		-y|--yes)        ASSUME_YES=1; shift ;;
		-q|--quiet)      QUIET=1; shift ;;
		-j|--jobs)       JOBS="${2:?-j needs a number}"; shift 2 ;;
		-p|--port)       PORT="${2:?-p needs a path}"; shift 2 ;;
		-a|--artifacts)  ARTIFACTS="${2:?-a needs a directory}"; shift 2 ;;
		-h|--help)       usage; exit 0 ;;
		--check|--build|--verify|--flash|--test|--all|--repro|--recover|--status)
		                 ACTION="${1#--}"; shift ;;
		*)               red "unknown option: $1"; usage; exit 1 ;;
	esac
done

if [ -n "$ARTIFACTS" ] && [ ! -d "$ARTIFACTS" ]; then
	die "artifacts directory does not exist: $ARTIFACTS"
fi

case "$ACTION" in
	check)   check_env ;;
	build)   do_build ;;
	verify)  do_verify ;;
	flash)   do_flash ;;
	test)    do_test ;;
	all)     do_all ;;
	repro)   do_repro ;;
	recover) do_recover ;;
	status)  do_status ;;
	"")      menu ;;
esac
