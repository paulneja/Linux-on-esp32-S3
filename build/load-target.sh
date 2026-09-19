#!/bin/bash

# Load target configuration from build/targets.json.
#
# Required:
#   TARGET
#
# Sets:
#   PROFILE
#   PARTITION_CSV
#   FLASH_SIZE
#   FLASH_BYTES
#   HAS_HOME
#   ROOTFS_LIMIT
#   KERNEL_LIMIT
#   KERNEL_CONFIG

_target_config_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
_target_config_json="$_target_config_dir/targets.json"

if [ -z "${TARGET:-}" ]; then
    echo "error: TARGET is not set" >&2
    return 1 2>/dev/null || exit 1
fi

_target_values=$(
    python3 - "$_target_config_json" "$TARGET" <<'PY'
import json
import shlex
import sys

path, target = sys.argv[1:3]

with open(path, encoding="utf-8") as f:
    targets = json.load(f)

if target not in targets:
    print(f"error: unknown TARGET={target}", file=sys.stderr)
    print("supported targets: " + " ".join(targets), file=sys.stderr)
    sys.exit(1)

c = targets[target]

values = {
    "PROFILE": c["profile"],
    "PARTITION_CSV": c["partition_csv"],
    "FLASH_SIZE": c["flash_size"],
    "FLASH_BYTES": c["flash_bytes"],
    "HAS_HOME": 1 if c["has_home"] else 0,
    "ROOTFS_LIMIT": c["rootfs_limit"],
    "KERNEL_LIMIT": c["kernel_limit"],
    "KERNEL_CONFIG": c["kernel_config"],
}

for key, value in values.items():
    print(f"{key}={shlex.quote(str(value))}")
PY
) || {
    return 1 2>/dev/null || exit 1
}

eval "$_target_values"

unset _target_values
unset _target_config_json
unset _target_config_dir
