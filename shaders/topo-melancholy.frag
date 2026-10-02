#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    vec2 resolution;
} ubuf;

// Thin contour line at the isovalue crossings of a smooth field.
float lineBand(float value, float width)
{
    return smoothstep(width, 0.0, abs(fract(value) - 0.5) - 0.28);
}

void main()
{
    vec2 uv = qt_TexCoord0;
    vec2 p = uv * 2.0 - 1.0;
    p.x *= ubuf.resolution.x / max(ubuf.resolution.y, 1.0);

    // Real-time pacing for the 2 fps repaint: the contour lines crawl a few
    // pixels per frame - slow, and smooth at every frame.
    float t = ubuf.time;
    vec2 drift = vec2(cos(t * 0.16), sin(t * 0.13)) * 0.16;
    vec2 q = p + drift;

    // Three interfering trig fields -> organic terrain from pure sines,
    // zero noise, zero hashes.
    float broad = sin(q.x * 3.1 + sin(q.y * 2.3 + t * 0.22) * 0.9 + t * 0.13);
    float cross = sin((q.x - q.y) * 4.6 - t * 0.19);
    float rings = sin(length(q - vec2(0.58, -0.24)) * 11.0 - t * 0.30);
    float rings2 = sin(length(q - vec2(-0.58, 0.34)) * 7.5 - t * 0.20);
    float field = broad * 0.44 + cross * 0.26 + rings * 0.22 + rings2 * 0.16;

    float gv = field * 2.2 + t * 0.18;
    float g1 = lineBand(gv, 0.028);                          // 1 outside, 0 in the groove
    float rim = clamp(lineBand(gv + 0.045, 0.028) - g1, 0.0, 1.0);   // lit ridge hugging one side
    float fh = (q.x * 8.5 + q.y * 5.0 + field * 1.4) - t * 0.19;
    float g2 = lineBand(fh, 0.020);
    float rim2 = clamp(lineBand(fh + 0.030, 0.020) - g2, 0.0, 1.0);

    // Composition: warm ember focal lower-right, cold teal focal upper-left,
    // a diagonal band of light across the middle.
    // The foci pulse on slow ~30-45 s cycles.
    float halo1 = smoothstep(0.85, 0.20, abs(length(q - vec2(0.62, -0.28)) - 0.42))
                * (0.80 + 0.35 * sin(t * 0.21));
    float halo2 = smoothstep(0.95, 0.18, abs(length(q - vec2(-0.58, 0.34)) - 0.45))
                * (0.80 + 0.35 * sin(t * 0.14 + 1.0));
    float band = smoothstep(0.62, 0.0, abs(p.y + p.x * 0.28 + 0.18 + sin(t * 0.12 + p.x * 1.4) * 0.08));
    float vignette = 1.0 - 0.50 * smoothstep(0.9, 2.3, length(p));   // gentle: corners ~0.55

    // Melancholy dusk palette: indigo ground; plum / steel / wine terrain
    // strata; a rose band; ember and teal foci. All hues desaturated.
    vec3 base  = mix(vec3(0.018, 0.020, 0.042),          // indigo black
                     vec3(0.048, 0.036, 0.064),          // plum lift
                     0.35 + 0.30 * q.y);
    vec3 plum  = vec3(0.260, 0.160, 0.330);
    vec3 steel = vec3(0.160, 0.240, 0.370);
    vec3 wine  = vec3(0.390, 0.140, 0.190);
    vec3 rose  = vec3(0.520, 0.310, 0.390);
    vec3 ember = vec3(0.600, 0.360, 0.160);
    vec3 teal  = vec3(0.130, 0.340, 0.370);

    vec3 color = base;
    color += plum  * (0.26 + 0.18 * broad);
    color += steel * (0.16 + 0.12 * cross);
    color += wine  * (0.16 + 0.12 * rings);
    color += rose  * (0.10 * band);
    color += ember * (0.20 * halo1);
    color += teal  * (0.26 * halo2);

    // Contour lines: pale rose-steel in the cold half, warm ivory near the
    // ember focal, so the map carries hue across the frame.
    vec3 lineWarm = vec3(0.820, 0.700, 0.560);
    vec3 lineCool = vec3(0.660, 0.670, 0.780);
    vec3 linecol = mix(lineWarm, lineCool, clamp(0.5 - 0.75 * (halo1 - halo2), 0.0, 1.0));
    color += linecol * (0.050 * g1 + 0.22 * rim + 0.020 * g2 + 0.070 * rim2);
    color += vec3(0.90, 0.78, 0.60) * 0.10 * rim * halo1;

    color *= vignette;
    fragColor = vec4(max(color, vec3(0.0)), 1.0) * ubuf.qt_Opacity;
}
