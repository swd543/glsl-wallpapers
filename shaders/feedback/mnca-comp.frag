// Multiple-Neighborhoods CA — display composite, melancholy palette.
//
// State texture RGBA32F: R = state, G = trail, B = long-range term.
// Palette taken from shaders/ink-melancholy.frag: near-black plum base,
// wine + mauve body, pale-rose rims/crests, steel-blue ghosts and halos.
// The colony body must stay dark (deep wine/mauve); rose and ivory are
// reserved for the rim (positive s-minus-neighbourhood-mean) and the
// hottest cores, so a saturated plateau cannot blow out to bright pink.

#version 310 es
precision highp float;
precision highp int;
precision highp sampler2D;

uniform sampler2D u_state;
uniform vec2 u_grid;
uniform vec2 u_res;

out vec4 fragColor;

float tap(vec2 uv, vec2 off)
{
    return texture(u_state, uv + off).r;
}

void main()
{
    vec2 uv = gl_FragCoord.xy / u_res;
    vec4 st = texture(u_state, uv);
    float s = st.r;
    float trail = st.g;
    float lr = st.b;

    vec2 off = 1.0 / u_grid;
    // 8-neighbourhood mean (rim detector + soft body)
    float n8 = (tap(uv, vec2(off.x, 0.0)) + tap(uv, vec2(-off.x, 0.0))
              + tap(uv, vec2(0.0, off.y)) + tap(uv, vec2(0.0, -off.y)))
             + (tap(uv, off) + tap(uv, -off)
              + tap(uv, vec2(off.x, -off.y))
              + tap(uv, vec2(-off.x, off.y)));
    n8 *= 0.125;
    float rim = clamp(s - n8, 0.0, 1.0);          // + at colony edge
    float fill = smoothstep(0.12, 0.50, s);       // colony body
    float core = smoothstep(0.65, 0.95, s);       // hottest interiors only

    vec3 col = mix(vec3(0.005, 0.004, 0.011),
                   vec3(0.034, 0.010, 0.030),
                   clamp(n8 * 3.0, 0.0, 1.0));

    col += vec3(0.50, 0.065, 0.22) * fill * 0.42; // wine body
    col += vec3(0.22, 0.105, 0.30) * fill * 0.38; // mauve body
    col += vec3(0.115, 0.26, 0.55) * lr * 0.55;   // steel long-range halo
    col += vec3(0.70, 0.30, 0.48) * rim * 0.55 * fill; // rose rim crest
    col += vec3(0.85, 0.78, 0.85) * pow(core, 3.0) * 0.75; // ivory core

    // ghost of the receding field: steel-mauve, dim
    col += vec3(0.10, 0.16, 0.30) * max(trail - s, 0.0) * 0.50;

    vec2 p = uv - 0.5;
    col *= 1.0 - 0.45 * smoothstep(0.30, 0.75, length(p) * 1.4);

    fragColor = vec4(col, 1.0);
}
