#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    vec2 resolution;
} ubuf;

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

// One travelling wave contributes both a surface-gradient displacement and
// analytic curvature. The gradient makes the web flow; the Hessian controls
// optical focusing, so motion and brightness come from one water surface.
void addWave(vec2 p, vec2 dir, float frequency, float curvature,
             float speed, float phase, float t,
             inout vec2 grad,
             inout float hxx, inout float hyy, inout float hxy)
{
    float phi = dot(p, dir) * frequency + t * speed + phase;
    float sn = sin(phi);
    float cs = cos(phi);
    grad += dir * (curvature / frequency) * cs;
    float bend = -curvature * sn;
    hxx += bend * dir.x * dir.x;
    hyy += bend * dir.y * dir.y;
    hxy += bend * dir.x * dir.y;
}

// Soft-energy cellular field. Random feature strength bends the boundaries
// into smooth organic curves rather than straight Voronoi bisectors. Feature
// motion is deliberately tiny: the continuous water field supplies almost
// all motion, avoiding the synthetic "independently crawling cells" look.
void cells(vec2 vp, float t, out float e1, out float e2, out float e3)
{
    vec2 ip = floor(vp);
    vec2 fp = fract(vp);
    e1 = 0.0;
    e2 = 0.0;
    e3 = 0.0;
    #define CELL(dx, dy) { \
        vec2 cid = ip + vec2(dx, dy); \
        float h = hash12(cid * 7.31 + 3.7); \
        vec2 rnd = vec2(fract(h * 13.71), fract(h * 7.31)); \
        vec2 point = 0.5 + (rnd - 0.5) * 0.70; \
        point += (rnd - 0.5) * (0.055 * sin(t * (0.18 + 0.08 * fract(h * 9.1)) \
                                                 + h * 6.28318)); \
        vec2 d = vec2(dx, dy) + point - fp; \
        float strength = 0.35 + 1.30 * fract(h * 5.77 + 0.31); \
        float en = strength / (dot(d, d) + 0.14); \
        if (en > e1) { e3 = e2; e2 = e1; e1 = en; } \
        else if (en > e2) { e3 = e2; e2 = en; } \
        else if (en > e3) { e3 = en; } }
    CELL(0.0, 0.0) CELL(1.0, 0.0) CELL(-1.0, 0.0) CELL(0.0, 1.0) \
    CELL(0.0, -1.0) CELL(1.0, 1.0) CELL(-1.0, 1.0) CELL(1.0, -1.0) \
    CELL(-1.0, -1.0)
    #undef CELL
}

void main()
{
    vec2 uv = qt_TexCoord0;
    vec2 p = uv * 2.0 - 1.0;
    p.x *= ubuf.resolution.x / max(ubuf.resolution.y, 1.0);
    float t = ubuf.time * 0.5;

    vec2 grad = vec2(0.0);
    float hxx = 0.0;
    float hyy = 0.0;
    float hxy = 0.0;

    // An irregular, nearly isotropic water spectrum. Frequencies and phase
    // speeds are incommensurate so the surface never translates as one sheet.
    addWave(p, vec2( 1.000,  0.000), 2.65, 0.30, 0.46, 0.20, t, grad, hxx, hyy, hxy);
    addWave(p, vec2( 0.707,  0.707), 3.15, 0.27, 0.55, 2.10, t, grad, hxx, hyy, hxy);
    addWave(p, vec2( 0.000,  1.000), 3.75, 0.25, 0.64, 4.35, t, grad, hxx, hyy, hxy);
    addWave(p, vec2(-0.707,  0.707), 4.35, 0.23, 0.74, 1.30, t, grad, hxx, hyy, hxy);
    addWave(p, vec2(-0.940, -0.342), 5.05, 0.20, 0.84, 5.20, t, grad, hxx, hyy, hxy);
    addWave(p, vec2(-0.309, -0.951), 5.85, 0.17, 0.95, 3.25, t, grad, hxx, hyy, hxy);
    addWave(p, vec2( 0.669, -0.743), 6.75, 0.14, 1.08, 0.80, t, grad, hxx, hyy, hxy);
    addWave(p, vec2( 0.966,  0.259), 7.80, 0.11, 1.22, 4.75, t, grad, hxx, hyy, hxy);

    // Refracted ray displacement advects the whole web coherently. The broad
    // gradient moves the water mass; three smaller travelling ripples bend
    // each edge *within* a cell. Without this cell-scale curvature, even a
    // warped Voronoi field remains locally straight and reads as polygonal.
    vec2 d1 = vec2( 0.832,  0.555);
    vec2 d2 = vec2(-0.600,  0.800);
    vec2 d3 = vec2( 0.220, -0.976);
    vec2 fineWarp = d1 * sin(dot(p, d1) * 11.7 + t * 1.37)
                  + d2 * sin(dot(p, d2) * 14.9 - t * 1.71) * 0.70
                  + d3 * sin(dot(p, d3) * 18.3 + t * 2.03) * 0.45;
    // Broad slow density variation: some regions swell, others compress,
    // so cells arrive in clumps of sizes instead of one uniform pitch.
    float broad = vnoise(p * 1.15 + vec2(t * 0.021, t * 0.014));
    vec2 vp = (p + grad * 1.18 + fineWarp * 0.062)
            * (6.30 * (0.86 + 0.28 * broad));
    float e1, e2, e3;
    cells(vp, t, e1, e2, e3);
    // A finer second web at its own scale and clock: real water carries
    // several interference scales, so a fine filament mesh crawls over the
    // broad one without ever repeating in sync with it.
    float eFA, eFB, eFC;
    cells(vp * 2.45 + vec2(37.13, 19.31), t * 0.9 + 7.0, eFA, eFB, eFC);

    float ratio = e2 / max(e1, 1e-4);       // 1 on a cell boundary
    float near3 = e3 / max(e1, 1e-4);       // 1 near a three-way junction
    float vertex = smoothstep(0.82, 1.0, near3);
    float ratioF = eFB / max(eFA, 1e-4);

    // Real optical focusing from the same surface. det(J)=0 is a fold
    // caustic. It controls both brightness AND ribbon width: focused segments
    // become broad/hot, while unfocused segments tighten or disappear.
    float eta = 2.35;
    float detJ = (1.0 + eta * hxx) * (1.0 + eta * hyy)
               - eta * eta * hxy * hxy;
    float focus = exp(-abs(detJ) * 2.6);
    float core = pow(ratio, mix(5.80, 3.40, focus));
    float halo = pow(ratio, 1.55) * 0.060;
    float fine = pow(ratioF, 3.20) * 0.11;
    float optical = 0.34 + 0.84 * focus;

    // Regional depth: low-frequency brightness variation, like light through
    // uneven water depth — some areas of the web run deeper than others.
    float depth = 0.78 + 0.40 * vnoise(p * 0.95 + vec2(t * 0.017, -t * 0.011));

    // Edges swell toward their midpoint (away from the vertices), the way a
    // caustic ribbon gathers light between folds; vertices stay the hottest
    // points via the separate star term.
    float glow = (core + halo) * (0.55 + 0.45 * near3)
               * optical * (1.0 + 0.38 * vertex) * 0.92;
    glow += pow(near3, 6.0) * 0.16;           // hot point at true vertices
    glow += fine * 0.65;                       // faint independent mesh
    glow += pow(near3, 2.2) * 0.018;           // ghost front
    glow *= depth;

    // Photographic micro-texture: real focused light is not a perfectly
    // smooth stroke; a whisper of high-frequency grain breaks the vector-art
    // edge without turning into visible noise.
    float grain = 0.90 + 0.10 * vnoise(p * 22.0 + t * 0.35);

    // Fine scintillation rides along the continuously varying wave curvature;
    // no per-cell constants, no checkerboards or bullseye rings.
    float shimmer = 0.88 + 0.12
                  * sin(t * 1.25 + hxx * 4.1 - hyy * 3.6 + hxy * 5.2);
    glow *= shimmer * grain;

    vec3 color = vec3(0.0015, 0.0035, 0.0070);
    color += vec3(0.88, 0.92, 1.00) * glow * 0.92;
    color += vec3(1.0) * smoothstep(0.82, 1.18, glow) * 0.18;

    float vignette = 1.0 - smoothstep(0.42, 1.35, length(uv * 2.0 - 1.0));
    color *= mix(0.44, 1.0, vignette) * 1.02;
    color = max(color, vec3(0.0));

    fragColor = vec4(color, 1.0) * ubuf.qt_Opacity;
}
