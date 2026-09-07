#!/usr/bin/env bash
set -uo pipefail

REPO=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$REPO" || exit 1

JOBS=${JOBS:-$( (nproc 2>/dev/null || echo 4) )}
PORT=${PORT:-}
ARTIFACTS=${ARTIFACTS:-}
ASSUME_YES=0
ACTION=""
LOGDIR=${LOGDIR:-$(dirname "$REPO")}
BOARD_ID_HINT="usb-1a86"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
warn()  { printf '  ! %s\n' "$*" >&2; }
info()  { printf '  %s\n' "$*"; }
die()   { red "error: $*"; exit 1; }

ask() {
	[ "$ASSUME_YES" = 1 ] && return 0
	local reply
	printf '%s [s/N] ' "$1"
	read -r reply </dev/tty 2>/dev/null || return 1
	case "$reply" in [sSyY]*) return 0 ;; *) return 1 ;; esac
}

usage() {
	cat <<'EOF'
Uso: ./run.sh [opciones] [accion]

Sin accion abre el menu interactivo.

Acciones:
  --check        Comprobar el entorno y arreglar lo que se pueda
  --build        Compilar todo desde fuentes limpias
  --verify       Comprobar los checksums de una compilacion
  --flash        Escribir la imagen en la placa (BORRA /etc y /home)
  --test         Ejecutar la bateria de pruebas en la placa
  --all          check, build, verify, flash y test, en ese orden
  --repro        Dos compilaciones del mismo commit y comparacion
  --recover      Devolver /etc y /home de la placa al estado de fabrica
  --status       Mostrar compilaciones existentes y estado de la placa

Opciones:
  -y, --yes            No preguntar; asumir que si
  -j, --jobs N         Trabajos paralelos de compilacion (por defecto: nproc)
  -p, --port RUTA      Adaptador serie (por defecto: autodeteccion)
  -a, --artifacts DIR  Directorio de artefactos a usar
  -h, --help           Esta ayuda
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
	warn "el puerto esta ocupado por:"
	for pid in $pids; do
		info "  pid $pid  $(ps -o args= -p "$pid" 2>/dev/null | cut -c1-70)"
	done
	warn "una consola abierta roba bytes y ademas resetea la placa al abrirse"
	if ask "  Cerrar esos procesos?"; then
		for pid in $pids; do kill "$pid" 2>/dev/null; done
		sleep 1
		for pid in $(port_holders "$port"); do kill -9 "$pid" 2>/dev/null; done
		sleep 1
		[ -z "$(port_holders "$port")" ] && { green "  puerto liberado"; return 0; }
		warn "no pude liberarlo"
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
	warn "el arbol no esta limpio y reproduce.sh toma la instantanea de HEAD:"
	printf '%s\n' "$dirty" | sed 's/^/      /'
	stray=$(printf '%s\n' "$dirty" | awk '$1=="??" && $2 ~ /\.log$/ {print $2}')
	if [ -n "$stray" ]; then
		if ask "  Mover los .log sueltos fuera del repositorio?"; then
			for f in $stray; do
				mv "$REPO/$f" "$LOGDIR/" 2>/dev/null && info "movido: $f -> $LOGDIR/"
			done
		fi
	fi
	dirty=$(git -C "$REPO" status --porcelain 2>/dev/null)
	[ -z "$dirty" ] && { green "  arbol limpio"; return 0; }
	warn "quedan cambios sin commitear; commitealos o guardalos antes de compilar"
	return 1
}

check_env() {
	bold "== Entorno =="
	local problems=0 py free port

	for c in git docker python3 sha256sum awk; do
		if have "$c"; then info "ok       $c"; else red "  falta    $c"; problems=$((problems+1)); fi
	done

	if docker info >/dev/null 2>&1; then
		info "ok       docker responde"
	else
		red "  problema docker no responde (servicio parado o falta permiso de grupo)"
		info "         probá: systemctl --user start docker  |  sudo usermod -aG docker \$USER"
		problems=$((problems+1))
	fi

	if have esptool || have esptool.py; then
		info "ok       esptool"
	else
		red "  falta    esptool"
		info "         instalá con: pipx install esptool   (o pip install --user esptool)"
		problems=$((problems+1))
	fi

	if py=$(python_with_pyserial); then
		info "ok       pyserial en $py"
	else
		red "  falta    pyserial (lo necesita la bateria de pruebas)"
		info "         instalá con: pipx inject esptool pyserial   (o pip install --user pyserial)"
		problems=$((problems+1))
	fi

	free=$(disk_free_gb)
	if [ -n "$free" ] && [ "$free" -ge 25 ] 2>/dev/null; then
		info "ok       disco: ${free} GB libres"
	else
		red "  problema disco: ${free:-?} GB libres; una compilacion ocupa ~21 GB"
		problems=$((problems+1))
	fi

	if port=$(detect_port); then
		info "ok       placa en $port"
		[ -n "$(port_holders "$port")" ] && warn "el puerto esta ocupado (ver opcion de liberar)"
	else
		warn "no se detecta ningun adaptador serie; conectá la placa para flashear"
	fi

	if [ -d "$REPO/.git" ]; then
		info "ok       commit $(git -C "$REPO" rev-parse --short HEAD 2>/dev/null) en $(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null)"
	fi

	echo
	if [ "$problems" -eq 0 ]; then green "Sin problemas."; else red "$problems problema(s) que hay que resolver."; fi
	return "$problems"
}

do_status() {
	bold "== Compilaciones =="
	local a manifest
	if [ -z "$(builds)" ]; then
		info "ninguna todavia"
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
      '| imagen', m.get('sha256', {}).get('linux-esp32s3-native-full.bin', '?')[:16],
      '| placa', v if isinstance(v, str) else v.get('status', '?'))
PY
			fi
		done < <(builds)
	fi
	echo
	bold "== Placa =="
	local port
	if port=$(detect_port); then
		info "puerto $port"
		local h; h=$(port_holders "$port")
		[ -n "$h" ] && warn "ocupado por: $h" || info "libre"
	else
		info "no detectada"
	fi
}

do_build() {
	bold "== Compilar desde fuentes limpias =="
	have docker || die "falta docker"
	docker info >/dev/null 2>&1 || die "docker no responde"
	local free; free=$(disk_free_gb)
	if [ -n "$free" ] && [ "$free" -lt 25 ] 2>/dev/null; then
		warn "solo ${free} GB libres y la compilacion ocupa ~21 GB"
		ask "  Continuar igual?" || return 1
	fi
	clean_tree_or_fix || return 1
	local log="$LOGDIR/esp32-build-$(date +%Y%m%d-%H%M%S).log"
	info "jobs: $JOBS"
	info "log:  $log"
	info "esto tarda del orden de 40 minutos"
	JOBS="$JOBS" bash "$REPO/build/reproduce.sh" > "$log" 2>&1
	local rc=$?
	if [ "$rc" -ne 0 ]; then
		red "la compilacion fallo (codigo $rc)"
		info "ultimas lineas:"
		tail -15 "$log" | sed 's/^/      /'
		return 1
	fi
	ARTIFACTS=$(builds | head -1)
	green "listo: ${ARTIFACTS#$REPO/}"
}

do_verify() {
	bold "== Comprobar checksums =="
	local a; a=$(latest_artifacts) || { red "no hay artefactos; compilá primero"; return 1; }
	info "${a#$REPO/}"
	[ -f "$a/SHA256SUMS" ] || { red "falta SHA256SUMS"; return 1; }
	if ( cd "$a" && sha256sum -c SHA256SUMS ) | sed 's/^/  /'; then
		green "todos los artefactos coinciden"
		return 0
	fi
	red "hay artefactos que no coinciden con su checksum"
	return 1
}

do_flash() {
	bold "== Flashear =="
	local a port
	a=$(latest_artifacts) || { red "no hay artefactos; compilá primero"; return 1; }
	port=$(detect_port) || { red "no se detecta la placa; pasá -p RUTA"; return 1; }
	info "imagen: ${a#$REPO/}"
	info "puerto: $port"
	red   "esto BORRA /etc y /home de la placa"
	ask "  Escribir la imagen?" || { info "cancelado"; return 1; }
	free_port "$port" || { red "liberá el puerto y volvé a intentar"; return 1; }
	"$REPO/flash.sh" -p "$port" --images "$a"
	local rc=$?
	[ "$rc" -eq 0 ] && green "flasheo terminado" || red "el flasheo fallo (codigo $rc)"
	return "$rc"
}

do_test() {
	bold "== Bateria de pruebas en la placa =="
	local a port py out n
	a=$(latest_artifacts) || { red "no hay artefactos"; return 1; }
	port=$(detect_port) || { red "no se detecta la placa"; return 1; }
	py=$(python_with_pyserial) || { red "no hay python con pyserial"; info "instalá con: pipx inject esptool pyserial"; return 1; }
	free_port "$port" || return 1
	out="$REPO/build-output/board-check"
	n=2
	while [ -e "$out" ]; do out="$REPO/build-output/board-check-$n"; n=$((n+1)); done
	info "salida: ${out#$REPO/}"
	info "26 pruebas, unos 5 minutos"
	"$py" "$REPO/build/test-board.py" "$port" "$a" --output "$out" --reset-from-bootloader
	local rc=$?
	if [ -f "$out/results.json" ]; then
		python3 - "$out/results.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
bad = [t['name'] for t in r['tests'] if t['status'] != 'pass']
print(f"  {r['status'].upper()}: {len(r['tests'])} pruebas, {len(bad)} fallidas")
for name in bad:
    print('    falla:', name)
PY
	fi
	if [ "$rc" -ne 0 ]; then
		red "la bateria no paso"
		warn "si se corto a la mitad quedan usuarios de prueba en la placa;"
		warn "usá la opcion de recuperar antes de reintentar"
		return 1
	fi
	green "todas las pruebas pasaron"
}

do_recover() {
	bold "== Devolver /etc y /home al estado de fabrica =="
	local a port
	a=$(latest_artifacts) || { red "no hay artefactos de donde sacar las particiones"; return 1; }
	port=$(detect_port) || { red "no se detecta la placa"; return 1; }
	for f in etc.jffs2 home.jffs2; do
		[ -f "$a/$f" ] || { red "falta $a/$f"; return 1; }
	done
	red "esto borra los datos actuales de /etc y /home de la placa"
	ask "  Continuar?" || return 1
	free_port "$port" || return 1
	local tool; tool=$(have esptool && echo esptool || echo esptool.py)
	"$tool" --chip esp32s3 --port "$port" --baud 460800 \
		--before default-reset --after no-reset \
		write-flash 0xd0000 "$a/etc.jffs2" 0xcc0000 "$a/home.jffs2"
	local rc=$?
	[ "$rc" -eq 0 ] && green "particiones restauradas" || red "fallo la restauracion"
	return "$rc"
}

do_repro() {
	bold "== Reproducibilidad: dos compilaciones del mismo commit =="
	local first second
	first=$(builds | head -1)
	if [ -z "$first" ]; then
		info "no hay ninguna compilacion; hago la primera"
		do_build || return 1
		first=$(builds | head -1)
	else
		info "primera: ${first#$REPO/}"
	fi
	info "ahora la segunda, del mismo commit"
	do_build || return 1
	second=$(builds | head -1)
	if [ "$second" = "$first" ]; then red "no aparecio una segunda compilacion"; return 1; fi
	bold "== Comparacion =="
	python3 "$REPO/build/compare-builds.py" "${first%/artifacts}" "${second%/artifacts}"
}

do_all() {
	check_env || { ask "  Hay problemas. Continuar igual?" || return 1; }
	do_build   || return 1
	do_verify  || return 1
	do_flash   || return 1
	do_test    || return 1
	green "camino completo terminado"
}

menu() {
	while true; do
		echo
		bold "=== Linux on ESP32-S3 ==="
		cat <<'EOF'
  1) Comprobar el entorno
  2) Compilar todo desde fuentes limpias
  3) Comprobar checksums de una compilacion
  4) Flashear la placa
  5) Ejecutar la bateria de pruebas
  6) TODO: compilar, comprobar, flashear y probar
  7) Reproducibilidad: dos compilaciones y comparar
  8) Recuperar la placa (restaurar /etc y /home)
  9) Estado
  0) Salir
EOF
		printf 'Opcion: '
		local choice
		read -r choice </dev/tty 2>/dev/null || return 0
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
			*) warn "opcion invalida" ;;
		esac
	done
}

while [ $# -gt 0 ]; do
	case "$1" in
		-y|--yes)        ASSUME_YES=1; shift ;;
		-j|--jobs)       JOBS="${2:?-j necesita un numero}"; shift 2 ;;
		-p|--port)       PORT="${2:?-p necesita una ruta}"; shift 2 ;;
		-a|--artifacts)  ARTIFACTS="${2:?-a necesita un directorio}"; shift 2 ;;
		-h|--help)       usage; exit 0 ;;
		--check|--build|--verify|--flash|--test|--all|--repro|--recover|--status)
		                 ACTION="${1#--}"; shift ;;
		*)               red "opcion desconocida: $1"; usage; exit 1 ;;
	esac
done

if [ -n "$ARTIFACTS" ] && [ ! -d "$ARTIFACTS" ]; then
	die "no existe el directorio de artefactos: $ARTIFACTS"
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
