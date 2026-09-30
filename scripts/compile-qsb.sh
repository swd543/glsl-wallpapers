#!/usr/bin/env bash
# Compile every shaders/*.frag into shaders/*.frag.qsb using the same
# invocation the original project used (verified byte-identical against the
# installed .qsb files): qsb-qt6 --qt6 -o OUT IN
#
# Then re-dump the QSB (-d) as a validity check.
set -euo pipefail

root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
shader_dir="${root_dir}/shaders"

if [[ ! -d "${shader_dir}" ]]; then
    echo "Missing shader directory: ${shader_dir}" >&2
    exit 1
fi

qsb_bin="${QSB_BIN:-}"
if [[ -z "${qsb_bin}" ]]; then
    for candidate in qsb-qt6 qsb /usr/lib64/qt6/bin/qsb /usr/lib/qt6/bin/qsb; do
        if command -v "${candidate}" >/dev/null 2>&1; then
            qsb_bin="${candidate}"
            break
        fi
    done
fi
if [[ -z "${qsb_bin}" ]]; then
    echo "Missing qsb. Install with: sudo dnf install qt6-qtshadertools" >&2
    exit 1
fi

count=0
while IFS= read -r -d '' frag; do
    count=$((count + 1))
    out="${frag}.qsb"
    echo "Compiling ${frag##*/} -> ${out##*/}"
    "${qsb_bin}" --qt6 -o "${out}" "${frag}"
    "${qsb_bin}" -d "${out}" >/dev/null
done < <(find "${shader_dir}" -type f -name '*.frag' -print0 | sort -z)

if [[ "${count}" -eq 0 ]]; then
    echo "No .frag files found under ${shader_dir}" >&2
    exit 1
fi

echo "Done: ${count} shader(s) compiled with $(command -v "${qsb_bin}")."
