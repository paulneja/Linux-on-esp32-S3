case $- in *i*) ;; *) return 0 ;; esac
[ -n "${BASH_VERSION-}" ] || return 0

: "${LOWMEM_DASH:=/usr/bin/dash}"
: "${LOWMEM_ENV:=/etc/dash-resume}"
: "${LOWMEM_RESUME:=/run/shell-resume}"
: "${LOWMEM_THRESHOLD:=900}"

__lowmem_last=
__lowmem_st=0
__lowmem_avail=0

# No command substitution anywhere in this file: a fork is the one thing that
# is known to be failing when this code has to work.
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

# 126 is what bash returns when it could not fork: jobs.c calls
# set_exit_status(EX_NOEXEC) and throws to the top level. Triggering on any
# non-zero status instead caught grep finding nothing, a failed test, and
# every ordinary command error -- and then re-ran them. Checking the status
# first also means /proc/meminfo is not read on every single prompt.
__lowmem_check() {
	[ "$1" = 126 ] || return 0
	[ -x "$LOWMEM_DASH" ] || return 0
	__lowmem_read_avail
	[ "$__lowmem_avail" -lt "$LOWMEM_THRESHOLD" ] || return 0
	printf '%s\n' "$__lowmem_last" > "$LOWMEM_RESUME.$$" 2>/dev/null
	printf 'bash could not fork with %s KiB free; switching this session to dash.\n' \
		"$__lowmem_avail" >&2
	printf 'Only this session changes. Make it permanent with: use-shell dash\n' >&2
	ENV="$LOWMEM_ENV" exec "$LOWMEM_DASH" -l -i
}

trap '__lowmem_st=$?; case $BASH_COMMAND in __lowmem*) ;; *) __lowmem_last=$BASH_COMMAND ;; esac' DEBUG
PROMPT_COMMAND='__lowmem_check "$__lowmem_st"'
