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
    // fixed patterns. Two cheap hashes replace the old fixed sine modulations.
    float wSlot = floor(t * 0.125);
    float wFrac = fract(t * 0.125);
    float wMix = wFrac * wFrac * (3.0 - 2.0 * wFrac);
    float wr = hash12(vec2(wSlot * 1.618 + 7.31, wSlot * 0.414 + 2.93));
    float pr = hash12(vec2((wSlot - 1.0) * 1.618 + 7.31,
                           (wSlot - 1.0) * 0.414 + 2.93));
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

    // Pseudo-random droplets. Each broad time slot gets one cheap hash,
    // which determines its wait, duration, travel direction, chord, arc and
    // shape. The orientation is fully random (360 degrees): every drop enters
    // at one edge of the frame and leaves at the opposite, so randomized
    // pacing never introduces a visible pop at slot boundaries.
    float dropSlot = floor(t * 0.09);
    float slotPhase = fract(t * 0.09);
    float dropRnd = hash12(vec2(dropSlot * 7.13 + 3.1,
                                dropSlot * 1.71 + 9.2));
    float rnd2 = fract(dropRnd * 17.17 + 0.31);
    float rnd3 = fract(dropRnd * 47.53 + 0.73);
    float dropStart = 0.08 + 0.24 * rnd2;
    float dropDuration = 0.34 + 0.26 * rnd3;
    float fallPhase = clamp((slotPhase - dropStart) / dropDuration, 0.0, 1.0);
    // Ease-out progress: the drop moves fast at first, then drifts slowly.
    float fallEase = 1.0 - (1.0 - fallPhase) * (1.0 - fallPhase);
    // Dissipation: in the second half the drop fades and spreads out, so it
    // melts away before reaching the far edge.
    float dissolve = 1.0 - smoothstep(0.50, 1.0, fallPhase);
    // Roughly one slot in seven stays empty, producing occasional long pauses.
    float dropEnabled = step(0.14, rnd3);
    float dropActive = step(dropStart, slotPhase)
                     * (1.0 - step(dropStart + dropDuration, slotPhase))
                     * dropEnabled;
    // Random travel direction and the frame chord it follows. The chord
    // parameters include a margin so the drop core starts and ends fully
    // outside the visible frame.
    vec2 dropDir = vec2(sin(dropRnd * 6.28318), cos(dropRnd * 6.28318));
    vec2 dropPerp = vec2(-dropDir.y, dropDir.x);
    float halfW = ubuf.resolution.x / max(ubuf.resolution.y, 1.0);
    vec2 dirSign = sign(dropDir);
    vec2 dropChordC = vec2(mix(-0.25, 0.25, rnd2),
                           mix(-0.18, 0.18, rnd3));
    float chordT = min((halfW - dropChordC.x * dirSign.x)
                       / max(abs(dropDir.x), 0.001),
                       (1.00 - dropChordC.y * dirSign.y)
                       / max(abs(dropDir.y), 0.001)) + 0.50;
    vec2 dropEntry = dropChordC - dropDir * chordT;
    float arc = sin(fallPhase * 3.14159 + rnd2 * 6.28318)
              * (0.05 + 0.10 * rnd3);
    vec2 dropCenter = dropEntry + dropDir * (fallEase * chordT * 2.0)
                    + dropPerp * arc;
    vec2 dropDelta = flowP - dropCenter;
    // Streak shape elongated along the direction of travel; spreads as the
    // drop dissolves.
    vec2 localDrop = vec2(dot(dropDelta, dropPerp), dot(dropDelta, dropDir));
    vec2 dropShape = localDrop * vec2(mix(1.85, 2.45, rnd2),
                                      mix(0.82, 1.05, rnd3))
                   * (1.0 + (1.0 - dissolve) * 0.55);
    float drop = (1.0 - smoothstep(0.025, 0.24, dot(dropShape, dropShape)))
               * dropActive * dissolve;
    // Local dimple dragged along the direction of travel.
    flowP += (dropDir * (0.18 + 0.13 * rnd3)
             - dropDelta * (0.06 + 0.06 * rnd2)) * drop;

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
    // The blend between the detail octaves also drifts pseudo-randomly.
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

    // Near-black plum water: deliberately low-key, with just enough wine in
    // the lifted areas to keep the marbling visible.
    vec3 color = mix(vec3(0.005, 0.004, 0.011),
                     vec3(0.034, 0.010, 0.030), clamp(f * 1.30, 0.0, 1.0));

    // Dark rose ink, sparse enough to leave broad melancholy shadows.
    float rose = smoothstep(0.39, 0.76, f) * (0.28 + 0.72 * detm);
    color += vec3(0.50, 0.065, 0.22) * rose * 0.78;

    // Smoky violet ink moves independently from the rose.
    float mauve = smoothstep(0.40, 0.78, g) * (0.30 + 0.70 * detm);

    // Sparse moonlit steel blue provides a quiet cool counterpoint. Its mask
    // is deliberately narrow and kept away from the strongest rose areas so
    // it supports the pink instead of competing with it.
    float blue = smoothstep(0.66, 0.90, g)
               * (1.0 - smoothstep(0.38, 0.60, f))
               * (0.30 + 0.70 * detm);
    color += vec3(0.22, 0.105, 0.30) * mauve * (1.0 - blue * 0.45) * 0.72;
    color += vec3(0.115, 0.26, 0.55) * blue * 0.60;

    // Overlaps bloom into a deeper magenta rather than white.
    float bloom = smoothstep(0.62, 0.88, min(f, g));
    color += vec3(0.38, 0.040, 0.18) * bloom * 0.34;

    // Restrained dusty-pink sheen on only the strongest crests.
    color += vec3(0.70, 0.30, 0.48)
             * smoothstep(0.90, 0.985, max(f, g)) * 0.20
             * (1.0 - blue * 0.55);

    // The falling droplet catches a very faint wine-colored glint.
    color += vec3(0.42, 0.055, 0.20) * drop * (0.035 + 0.08 * detm);

    // Micro-definition at no extra resolution cost: screen-space derivatives
    // give anti-aliased iso-lines that trace the ink folds, while flow-warped
    // sines add fine striations that follow the marbling instead of the grid.
    // Neither adds noise samples.
    float fGrad = fwidth(f) * 5.0 + 0.012;
    float gGrad = fwidth(g) * 4.2 + 0.012;
    float lineF = 1.0 - smoothstep(0.0, fGrad, abs(fract(f * 5.0 + 0.25) - 0.5));
    float lineG = 1.0 - smoothstep(0.0, gGrad, abs(fract(g * 4.2 - 0.35) - 0.5));
    vec2 rippleP = (q + 5.5 * q2);
    float ripple = sin(rippleP.x * 21.0 + f * 14.0 + det * 6.0)
                 * sin(rippleP.y * 19.0 - g * 11.0 + det2 * 5.0);
    float striation = smoothstep(0.62, 0.98, ripple * 0.5 + 0.5) * detm;

    color += vec3(0.45, 0.05, 0.16) * lineF * 0.10;
    color += vec3(0.10, 0.16, 0.30) * lineG * 0.07;
    color += vec3(0.62, 0.22, 0.36) * striation * 0.05;

    float vignette = 1.0 - smoothstep(0.42, 1.35, length(uv * 2.0 - 1.0));
    color *= mix(0.38, 1.0, vignette) * 0.98;
    color = max(color, vec3(0.0));

    fragColor = vec4(color, 1.0) * ubuf.qt_Opacity;
}
