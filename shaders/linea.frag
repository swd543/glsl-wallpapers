#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    vec2 resolution;
} ubuf;

void main()
{
    vec2 uv = qt_TexCoord0;
    vec2 p = uv * 2.0 - 1.0;
    p.x *= ubuf.resolution.x / max(ubuf.resolution.y, 1.0);

    // Animated at 1-2 fps by design: the fan carries a slow ripple that
    // crosses it in ~30 s and a ~45 s global breath; the circles drift on
    // ~2-4 minute Lissajous orbits. Each 1 s frame is a deliberate step.
    float t = ubuf.time;

    vec3 col = vec3(0.0);   // solid black ground

    // ---- concentric "line + arc" fan across the bottom-right corner ----
    // level sets of length(max(p,0)): straight runs parallel to the two
    // edges, joined by a rounded 90-degree bend at the corner.
    float asp = ubuf.resolution.x / max(ubuf.resolution.y, 1.0);
    vec2 c = vec2(asp, -1.0) + 0.020 * vec2(cos(t * 0.035), sin(t * 0.029));
    vec2 d = p - c;
    float r = length(vec2(max(-d.x, 0.0), max(d.y * 1.45, 0.0)));
    float v = r * 8.33
            + 0.120 * sin(r * 4.0 - t * 0.42)   // ripple crossing the fan in ~15 s
            + 0.080 * sin(t * 0.21);            // global breath, ~30 s
    float arc = 1.0 - smoothstep(0.130, 0.180, abs(fract(v) - 0.5));
    float mask = smoothstep(0.75, 0.85, r) * (1.0 - smoothstep(1.70, 1.80, r));
    float shade = 0.82 + 0.18 * fract(floor(v) * 1.713 + 0.37);  // per-arc tone
    float fall = 1.0 - 0.25 * (r - 0.75) / 1.05;             // inner arcs brighter
    col += vec3(0.29, 0.40, 0.62) * arc * mask * shade * fall;

    // ---- flat circles, roaming the left half ----
    // long Lissajous orbits (~3-4 min periods): they wander freely and
    // occasionally overlap, where the additive colours sum to a lighter tint.
    vec2 c1 = vec2(-1.46, 1.30) + 0.20 * vec2(sin(t * 0.029), cos(t * 0.023));
    vec2 c2 = vec2(-1.42, -0.15) + vec2(0.22 * sin(t * 0.034 + 2.0),
                                      0.26 * cos(t * 0.027 + 1.0));
    col += vec3(0.42, 0.55, 0.88) * (1.0 - smoothstep(0.900, 0.910, length(p - c1)));
    col += vec3(0.25, 0.34, 0.53) * (1.0 - smoothstep(0.420, 0.430, length(p - c2)));

    fragColor = vec4(col, 1.0) * ubuf.qt_Opacity;
}
