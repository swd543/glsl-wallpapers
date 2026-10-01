// Game of Life — CA step (one generation per frame).
//
// Feedback shader: NOT single-pass Plasma QSB. Ping-ponged by
// scripts/life-preview.py (design tool for the Android app's ping-pong
// port). State texture (RGBA8, cell-resolution, torus wrap):
//   R = alive (0/1)
//   G = energy 0..1 (glow / trail; fades by u_decay per frame)
//   B = live-neighbor count 0..8 (colored in the composite)
//
// "Merge" comes from the bloom term: dead cells touching live ones keep a
// faint charge, so adjacent masses bleed into each other.

#version 310 es
precision highp float;
precision highp int;

uniform sampler2D u_state;
uniform vec2 u_grid;    // cell count (x, y)
uniform float u_frame;  // generation counter (float, integer-valued)
uniform float u_decay;  // trail fade per frame (0.90..0.97)
uniform float u_rain;   // ambient reseed probability per cell per frame

out vec4 fragColor;

float hash12(vec2 p)
{
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

void main()
{
    vec2 cell = gl_FragCoord.xy - 0.5;
    vec2 uv = (cell + 0.5) / u_grid;
    vec3 s = texture(u_state, uv).rgb;  // NEAREST: exact cell state
    float alive = s.r;
    float n = 0.0;
    for (int dy = -1; dy <= 1; dy++) {
        for (int dx = -1; dx <= 1; dx++) {
            if (dx == 0 && dy == 0)
                continue;
            // torus wrap
            vec2 q = mod(cell + vec2(float(dx), float(dy)) + 0.5 * u_grid,
                         u_grid) - 0.5 * u_grid;
            n += texture(u_state, (q + 0.5) / u_grid).r;
        }
    }

    float next;
    if (n == 3.0)
        next = 1.0;
    else if (alive > 0.5 && n == 2.0)
        next = 1.0;
    else
        next = 0.0;

    float e;
    if (next > 0.5)
        e = 1.0;
    else
        // trail decay + merge bloom toward live neighbors
        e = s.g * u_decay + n * 0.045;

    // ambient rain: a few fresh cells per frame keep the field alive
    float r = hash12(cell + 0.5 * fract(
        vec2(u_frame * 0.6180339, u_frame * 0.3819661) * 7919.0));
    if (r < u_rain) {
        next = 1.0;
        e = 1.0;
    }

    fragColor = vec4(next, e, n, 1.0);
}
