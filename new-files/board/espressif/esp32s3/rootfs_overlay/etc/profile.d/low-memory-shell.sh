case $- in *i*) ;; *) return 0 ;; esac
[ -n "${BASH_VERSION-}" ] || return 0

: "${LOWMEM_DASH:=/usr/bin/dash}"
: "${LOWMEM_ENV:=/etc/dash-resume}"
: "${LOWMEM_RESUME:=/run/shell-resume}"
: "${LOWMEM_PREF:=$HOME/.shell}"
: "${LOWMEM_THRESHOLD:=900}"

__lowmem_last=
__lowmem_st=0
__lowmem_avail=0

__lowmem_read_avail() {
	local name rest
	__lowmem_avail=0
	while read -r name rest; do
		if [ "$name" = MemAvailable: ]; then
			set -- $rest
			__lowmem_avail=$1
			return 0
		fi
	done < /proc/meminfo
}

__lowmem_check() {
	[ "$1" = 0 ] && return 0
	[ -x "$LOWMEM_DASH" ] || return 0
	__lowmem_read_avail
	[ "$__lowmem_avail" -lt "$LOWMEM_THRESHOLD" ] || return 0
	printf '%s\n' "$__lowmem_last" > "$LOWMEM_RESUME" 2>/dev/null
	printf 'dash\n' > "$LOWMEM_PREF" 2>/dev/null
	printf 'bash cannot fork with %s KiB free; switching to dash and retrying.\n' \
		"$__lowmem_avail" >&2
	printf 'This choice persists across logins. Undo it with: use-shell bash\n' >&2
	ENV="$LOWMEM_ENV" exec "$LOWMEM_DASH" -i
}

trap '__lowmem_st=$?; case $BASH_COMMAND in __lowmem*) ;; *) __lowmem_last=$BASH_COMMAND ;; esac' DEBUG
PROMPT_COMMAND='__lowmem_check "$__lowmem_st"'
