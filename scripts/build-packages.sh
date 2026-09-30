#!/usr/bin/env bash
# Assemble per-variant, installable Plasma wallpaper plugin directories under
# build/, matching the layout of the installed org.local.axiom.shaderlogin.*
# plugins (metadata.json + contents/ui/{main.qml, *.frag, *.frag.qsb}).
#
# Nothing is installed here — the output is a payload. To install later:
#   sudo cp -r build/org.local.axiom.lockwall.<variant> /usr/share/plasma/wallpapers/
# then select it in kscreenlocker settings / /etc/plasmalogin.conf.
set -euo pipefail

root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
shader_dir="${root_dir}/shaders"
tmpl_dir="${root_dir}/templates"
build_dir="${root_dir}/build"
prefix="org.local.axiom.lockwall"

# 1. Compile all shaders (ensures fresh .qsb artifacts).
bash "${root_dir}/scripts/compile-qsb.sh"

# 2. Assemble the plugin dirs.
mkdir -p "${build_dir}"
found=0
while IFS= read -r -d '' frag; do
    found=1
    variant="$(basename "${frag}" .frag)"
    pkg_id="${prefix}.${variant}"
    # human-friendly name: ember-drift -> Ember Drift
    name="$(tr '-' ' ' <<<"${variant}" | sed -E 's/(\b[a-z])/\U\1/g')"
    # Domain-warped ink is the only expensive family. On the 4K lock screen,
    # rendering it at 67% linear resolution keeps frame pacing smooth while
    # smooth upscaling preserves the soft marbled look. Simple variants remain
    # native-res.
    case "${variant}" in
        ink|ink-melancholy) render_scale="0.67" ;;
        *)                   render_scale="1.0" ;;
    esac
    dst="${build_dir}/${pkg_id}/contents/ui"
    mkdir -p "${dst}"

    # All shaders + qsb (mirrors the installed layout where every variant
    # dir carries the full set).
    cp -f "${shader_dir}"/*.frag "${dst}/"
    cp -f "${shader_dir}"/*.frag.qsb "${dst}/"

    sed -e "s/@ID@/${pkg_id}/g" -e "s/@NAME@/Lockwall - ${name}/g" \
        "${tmpl_dir}/metadata.json.in" > "${build_dir}/${pkg_id}/metadata.json"
    sed -e "s|@SHADER@|${variant}.frag.qsb|g" \
        -e "s|@RENDER_SCALE@|${render_scale}|g" \
        "${tmpl_dir}/main.qml.in" > "${dst}/main.qml"

    echo "Built ${pkg_id}"
done < <(find "${shader_dir}" -type f -name '*.frag' -print0 | sort -z)

if [[ "${found}" -eq 0 ]]; then
    echo "No .frag files found under ${shader_dir}" >&2
    exit 1
fi

echo
echo "Payload ready under ${build_dir}/"
echo "Install (when wanted): sudo cp -r ${build_dir}/${prefix}.* /usr/share/plasma/wallpapers/"
