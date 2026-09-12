# Shell history lives in RAM, not on flash.
#
# /home is jffs2, and this project measured writes there taking seconds --
# putting a history file on it makes every interactive session pay for that.
# /tmp is tmpfs, so history works within a session and is gone at reboot.
#
# No command substitution: this is sourced by every login shell, and a fork
# is the expensive operation on this board.
HISTFILE=/tmp/.history-${USER:-${LOGNAME:-shell}}
HISTSIZE=200
HISTFILESIZE=200
export HISTFILE HISTSIZE HISTFILESIZE
