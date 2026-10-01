// Multiple-Neighborhoods Cellular Automaton — CA step (Softology-style).
//
// Continuous-state automaton (Lenia / Larger-Than-Life family): each cell's
// next state is a weighted sum of a rule curve applied to the mean state in
// each of THREE circular neighborhoods of different size:
//   N1: disk  r=2 (12 taps)  - local dynamics
//   N2: ring  r=3 (16 taps)  - mid-scale
//   N3: ring  r=4 (20 taps)  - long-range coupling
// The neighbourhood radius, not the rule curve, sets the colony scale:
// 1-2 cell neighbourhoods produce fine foam; these give 10-40 cell patches.
//
// Rule curve (a, b, c, d): zero below a and at/above c; a tent peaking
// with gain d at b. a = dead zone (keep it above the ambient base so the
// background cannot excite itself), b = preferred neighbourhood mean,
// c = over-density zero crossing, d = gain.
//
// Feedback shader: ping-ponged by the web preview (scripts/feedback.py).
// State texture is RGBA32F: R = state, G = trail, B = long-range term
// (for steel tinting).

#version 310 es
precision highp float;
precision highp int;
precision highp sampler2D;

uniform sampler2D u_state;
uniform vec2 u_grid;
uniform float u_frame;  // generation counter (drives the reseed hash)
uniform float u_decay;    // trail fade per frame
uniform float u_rain;     // ambient reseed: fresh colonies nucleate in dead space
uniform vec4 u_k1;        // a b c d for N1
uniform vec4 u_k2;        // N2
uniform vec4 u_k3;        // N3
uniform vec3 u_w;         // neighborhood weights

out vec4 fragColor;

float rule(float x, vec4 k)
{
    if (x < k.x || x >= k.z)
        return 0.0;
    if (x <= k.y)
        return k.w * (x - k.x) / (k.y - k.x);
    return k.w * (k.z - x) / (k.z - k.y);
}

float tap(vec2 c, vec2 off)
{
    vec2 q = mod(c + off + 0.5 * u_grid, u_grid) - 0.5 * u_grid;
    return texture(u_state, (q + 0.5) / u_grid).r;
}

void main()
{
    vec2 c = gl_FragCoord.xy - 0.5;
    vec4 s = texture(u_state, (c + 0.5) / u_grid);

    // N1: disk r=2 (12)
    float n1m = 0.0;
    n1m += tap(c, vec2(0.0, -2.0));
    n1m += tap(c, vec2(-1.0, -1.0));
    n1m += tap(c, vec2(0.0, -1.0));
    n1m += tap(c, vec2(1.0, -1.0));
    n1m += tap(c, vec2(-2.0, 0.0));
    n1m += tap(c, vec2(-1.0, 0.0));
    n1m += tap(c, vec2(1.0, 0.0));
    n1m += tap(c, vec2(2.0, 0.0));
    n1m += tap(c, vec2(-1.0, 1.0));
    n1m += tap(c, vec2(0.0, 1.0));
    n1m += tap(c, vec2(1.0, 1.0));
    n1m += tap(c, vec2(0.0, 2.0));
    n1m *= 1.0 / 12.0;

    // N2: ring r=3 (16)
    float n2m = 0.0;
    n2m += tap(c, vec2(0.0, -3.0));
    n2m += tap(c, vec2(-2.0, -2.0));
    n2m += tap(c, vec2(-1.0, -2.0));
    n2m += tap(c, vec2(1.0, -2.0));
    n2m += tap(c, vec2(2.0, -2.0));
    n2m += tap(c, vec2(-2.0, -1.0));
    n2m += tap(c, vec2(2.0, -1.0));
    n2m += tap(c, vec2(-3.0, 0.0));
    n2m += tap(c, vec2(3.0, 0.0));
    n2m += tap(c, vec2(-2.0, 1.0));
    n2m += tap(c, vec2(2.0, 1.0));
    n2m += tap(c, vec2(-2.0, 2.0));
    n2m += tap(c, vec2(-1.0, 2.0));
    n2m += tap(c, vec2(1.0, 2.0));
    n2m += tap(c, vec2(2.0, 2.0));
    n2m += tap(c, vec2(0.0, 3.0));
    n2m *= 1.0 / 16.0;

    // N3: ring r=4 (20)
    float n3m = 0.0;
    n3m += tap(c, vec2(0.0, -4.0));
    n3m += tap(c, vec2(-2.0, -3.0));
    n3m += tap(c, vec2(-1.0, -3.0));
    n3m += tap(c, vec2(1.0, -3.0));
    n3m += tap(c, vec2(2.0, -3.0));
    n3m += tap(c, vec2(-3.0, -2.0));
    n3m += tap(c, vec2(3.0, -2.0));
    n3m += tap(c, vec2(-3.0, -1.0));
    n3m += tap(c, vec2(3.0, -1.0));
    n3m += tap(c, vec2(-4.0, 0.0));
    n3m += tap(c, vec2(4.0, 0.0));
    n3m += tap(c, vec2(-3.0, 1.0));
    n3m += tap(c, vec2(3.0, 1.0));
    n3m += tap(c, vec2(-3.0, 2.0));
    n3m += tap(c, vec2(3.0, 2.0));
    n3m += tap(c, vec2(-2.0, 3.0));
    n3m += tap(c, vec2(-1.0, 3.0));
    n3m += tap(c, vec2(1.0, 3.0));
    n3m += tap(c, vec2(2.0, 3.0));
    n3m += tap(c, vec2(0.0, 4.0));
    n3m *= 1.0 / 20.0;

    float v1 = rule(n1m, u_k1) * u_w.x;
    float v2 = rule(n2m, u_k2) * u_w.y;
    float v3 = rule(n3m, u_k3) * u_w.z;
    float s2 = v1 + v2 + v3;

    // ambient reseed: a hash on the 2x2 block index + generation makes
    // sparse fresh colonies nucleate in dead space, so the field never
    // settles into a static attractor (a lone cell would die alone — the
    // block seeds a small blob that can grow)
    vec2 blk = floor(c * 0.5) * 2.0;
    float hsh = fract(sin(dot(blk + 0.5, vec2(12.9898, 78.233))
                        + u_frame * 0.173) * 43758.5453);
    s2 = max(s2, step(1.0 - u_rain, hsh) * 0.45);

    float trail = max(s.g * u_decay, s2);
    fragColor = vec4(s2, trail, v3, 1.0);
}
