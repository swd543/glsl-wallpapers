#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    vec2 resolution;
} ubuf;

// Texture-free value noise (hash-based, no textures, no loops).
float hash12(vec2 p)
{
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

float vnoise(vec2 p)
{
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash12(i), hash12(i + vec2(1.0, 0.0)), u.x),
               mix(hash12(i + vec2(0.0, 1.0)), hash12(i + vec2(1.0, 1.0)), u.x), u.y);
}

void main()
{
    vec2 uv = qt_TexCoord0;
    vec2 p = uv * 2.0 - 1.0;
    p.x *= ubuf.resolution.x / max(ubuf.resolution.y, 1.0);
    float t = ubuf.time * 0.5;

    // Pseudo-random "weather": hash the current and previous 8-second slots
    // and ease between the two targets, so eddy positions, strength, drift
    // direction and feature scale meander smoothly instead of repeating
    // fixed patterns. (Different seed from ink-melancholy so the two
    // variants wander independently.)
    float wSlot = floor(t * 0.125);
    float wFrac = fract(t * 0.125);
    float wMix = wFrac * wFrac * (3.0 - 2.0 * wFrac);
    float wr = hash12(vec2(wSlot * 1.618 + 13.77, wSlot * 0.414 + 8.41));
    float pr = hash12(vec2((wSlot - 1.0) * 1.618 + 13.77,
                           (wSlot - 1.0) * 0.414 + 8.41));
    vec2 wN = vec2(fract(wr * 31.71 + 0.43), fract(wr * 19.37 + 0.17)) - 0.5;
    vec2 pN = vec2(fract(pr * 31.71 + 0.43), fract(pr * 19.37 + 0.17)) - 0.5;
    vec2 meander = mix(pN, wN, wMix) * 0.95;
    float wAmp1 = mix(fract(pr * 41.93 + 0.71), fract(wr * 41.93 + 0.71), wMix);
    float wAmp2 = mix(fract(pr * 53.23 + 0.29), fract(wr * 53.23 + 0.29), wMix);
    float wScale = mix(fract(pr * 61.31 + 0.83), fract(wr * 61.31 + 0.83), wMix);

    // Layered motion field: two broad counter-rotating eddies with wandering
    // centers and randomized strength deform the coordinates locally, keeping
    // the marble from translating as one rigid sheet.
    vec2 flowP = p;
    vec2 v1 = flowP - (vec2(-0.52, 0.24) + meander * 0.55);
    vec2 v2 = flowP - (vec2( 0.58, -0.30) - meander * 0.45);
    float swirl1 = 1.0 - smoothstep(0.10, 1.35, dot(v1, v1));
    float swirl2 = 1.0 - smoothstep(0.08, 1.15, dot(v2, v2));
    flowP += vec2(-v1.y, v1.x) * swirl1 * (0.10 + 0.26 * wAmp1);
    flowP -= vec2(-v2.y, v2.x) * swirl2 * (0.08 + 0.24 * wAmp2);

    // Pseudo-random falling drops. Each broad time slot gets one cheap hash,
    // which determines its wait, fall duration, entry point, arc and shape.
    // Drops begin above and finish below the frame, so randomized pacing never
    // introduces a visible pop at slot boundaries.
    float dropSlot = floor(t * 0.09);
    float slotPhase = fract(t * 0.09);
    float dropRnd = hash12(vec2(dropSlot * 7.13 + 11.3,
                                dropSlot * 1.71 + 5.7));
    float rnd2 = fract(dropRnd * 17.17 + 0.31);
    float rnd3 = fract(dropRnd * 47.53 + 0.73);
    float dropStart = 0.08 + 0.24 * rnd2;
    float dropDuration = 0.34 + 0.26 * rnd3;
    float fallPhase = clamp((slotPhase - dropStart) / dropDuration, 0.0, 1.0);
    // Roughly one slot in seven stays empty, producing occasional long pauses.
    float dropEnabled = step(0.14, rnd3);
    float dropActive = step(dropStart, slotPhase)
                     * (1.0 - step(dropStart + dropDuration, slotPhase))
                     * dropEnabled;
    float dropX = mix(-0.72, 0.72, dropRnd)
                + sin(fallPhase * 3.14159 + rnd2 * 6.28318) * (0.05 + 0.10 * rnd3);
    vec2 dropCenter = vec2(dropX, 1.38 - fallPhase * 2.76);
    vec2 dropDelta = flowP - dropCenter;
    vec2 dropShape = dropDelta * vec2(mix(1.85, 2.45, rnd2),
                                      mix(0.82, 1.05, rnd3));
    float drop = (1.0 - smoothstep(0.025, 0.24, dot(dropShape, dropShape)))
               * dropActive;
    flowP += vec2(-dropDelta.x * (0.12 + 0.12 * rnd2),
                  0.18 + 0.13 * rnd3) * drop;

    // Independent clocks: the broad body drifts slowly, mid-sized folds slide
    // across it at another angle, and the fine tendrils move faster still.
    // The meander offset lets every clock's direction wander too.
    vec2 slowPhase = vec2(t * 0.040, -t * 0.027) + meander * 0.30;
    vec2 foldPhase = vec2(-t * 0.086, t * 0.061) + meander * 0.22;
    vec2 finePhase = vec2(t * 0.145, t * 0.097) + meander * 0.50;
    float fieldScale = 3.6 * (1.0 + (wScale - 0.5) * 0.14);
    vec2 q = flowP * fieldScale + slowPhase;

    // Two unrolled domain-warp iterations -> liquid marbling. Their channels
    // deliberately use different fractions of foldPhase so structures shear
    // past one another instead of translating as one sheet.
    vec2 q1 = vec2(vnoise(q + foldPhase * 0.24),
                   vnoise(q + vec2(4.7, -2.1) - foldPhase * 0.34));
    vec2 q2 = vec2(vnoise(q + 2.0 * q1 + vec2(2.3, 1.1) + foldPhase * 0.42),
                   vnoise(q + 1.6 * q1 + vec2(-1.1, 3.3) - foldPhase * 0.29));

    // Two fine detail octaves; their faster opposing phases make the tendrils
    // crawl over the slower ink bodies without adding another noise sample.
    float det  = vnoise(q * 4.0 + 5.1 * q1 + finePhase);
    float det2 = vnoise(q * 7.0 + 8.3 * q2 - finePhase * 0.78);
    // The blend between the two detail octaves also drifts pseudo-randomly.
    float detMix = 0.5 + (mix(fract(pr * 71.13 + 0.37),
                              fract(wr * 71.13 + 0.37), wMix) - 0.5) * 0.36;
    float detm = det * detMix + det2 * (1.0 - detMix);

    // Gold driver.
    float f = vnoise(q + 2.6 * q2 + foldPhase * 0.30
                     + 1.2 * (detm - 0.5) * 2.0);
    // Blue driver: an INDEPENDENT field (different base seed + weights) so the
    // blue ink marbles separately from the gold instead of tracking it.
    float g = vnoise(q * 0.92 + 7.31 + 1.8 * q1 - 1.6 * q2 + vec2(0.0, -1.9)
                     - foldPhase * 0.26 + 1.2 * (det - 0.5) * 2.0);

    // Deep green/teal water base (reads as dark green, not black).
    vec3 color = mix(vec3(0.034, 0.084, 0.068),
                     vec3(0.070, 0.150, 0.122), clamp(f * 1.5, 0.0, 1.0));

    // Gold ink.
    float gm = smoothstep(0.33, 0.68, f) * (0.35 + 0.65 * detm);
    color += vec3(0.88, 0.69, 0.25) * gm * 1.05;

    // Pale blue ink.
    float bm = smoothstep(0.31, 0.70, g) * (0.35 + 0.65 * detm);
    color += vec3(0.64, 0.82, 0.95) * bm * 1.15;

    // White sheen on the strongest crests of either ink.
    color += vec3(0.92, 0.96, 1.0) * smoothstep(0.84, 0.96, max(f, g)) * 0.50;

    // The falling droplet catches a faint warm glint.
    color += vec3(0.85, 0.70, 0.45) * drop * (0.030 + 0.050 * detm);

    float vignette = 1.0 - smoothstep(0.42, 1.35, length(uv * 2.0 - 1.0));
    color *= mix(0.52, 1.0, vignette) * 1.08;
    color = max(color, vec3(0.0));

    fragColor = vec4(color, 1.0) * ubuf.qt_Opacity;
}
