# Use nano as the default editor (busybox vi is disabled on this build).
# `vi` is a symlink to nano (see /usr/bin/vi), so no shell alias is needed --
# this shell has no `alias` builtin anyway.
export EDITOR=nano
export VISUAL=nano
