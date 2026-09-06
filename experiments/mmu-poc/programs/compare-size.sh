#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
for variant in baseline oz lto; do
    OPT_VARIANT=$variant bash "$experiment_dir/fork/real/build.sh" all \
        > "$programs_out/size-$variant-build.log" 2>&1
done
printf 'program,variant,file_bytes,text_bytes,data_bytes,bss_bytes\n'
for program in dash make; do
    for variant in baseline oz lto; do
        file="$experiment_dir/out/real-bins/$program-$variant"
        read -r text data bss _ < <("$prefix-size" "$file" | tail -n 1)
        printf '%s,%s,%s,%s,%s,%s\n' "$program" "$variant" "$(wc -c < "$file")" "$text" "$data" "$bss"
    done
done
