// Game of Life — display composite (cell state -> screen).
//
// Same state texture as life-ca.frag, sampled two ways:
//   u_lin  = bilinear  (energy field, for the soft glow)
//   u_near = nearest   (alive mask + neighbor count, for crisp cores)
//
// The merge bloom re-samples the energy at +-1 cell offsets, so live
// masses that sit next to each other light the bridge between them.

#version 310 es
precision highp float;
precision highp int;

uniform sampler2D u_lin;
uniform sampler2D u_near;
uniform vec2 u_grid;
uniform vec2 u_res;

out vec4 fragColor;

void main()
{
    vec2 uv = gl_FragCoord.xy / u_res;
    float e = texture(u_lin, uv).g;

    // merge bloom: orthogonal + diagonal neighbor energies
    vec2 off = 1.0 / u_grid;
    e += 0.20 * (
            texture(u_lin, uv + vec2(off.x, 0.0)).g
          + texture(u_lin, uv - vec2(off.x, 0.0)).g
          + texture(u_lin, uv + vec2(0.0, off.y)).g
          + texture(u_lin, uv - vec2(0.0, off.y)).g
        )
        + 0.08 * (
            texture(u_lin, uv + off).g
          + texture(u_lin, uv - off).g
          + texture(u_lin, uv + vec2(off.x, -off.y)).g
          + texture(u_lin, uv + vec2(-off.x, off.y)).g
        );
    e = clamp(e, 0.0, 1.0);

    vec2 ab = texture(u_near, uv).rb;   // (alive, neighbor count)
    float alive = ab.x;
    float nb = ab.y;

    // house dark palette: near-black teal base, steel glow, gold core.
    vec3 bg = vec3(0.010, 0.014, 0.020);
    vec3 steel = vec3(0.085, 0.160, 0.260);
    vec3 gold = vec3(0.98, 0.86, 0.55);

    // fresh singletons (gliders) read warm; dense clusters read cool
    float warm = 1.0 - 0.5 * clamp(nb / 6.0, 0.0, 1.0);
    vec3 core = mix(gold * vec3(1.05, 0.92, 0.70),
                    gold * vec3(0.80, 0.90, 1.00), 1.0 - warm);

    float glow = smoothstep(0.015, 0.60, e);
    vec3 col = bg + steel * glow * 0.85;
    col += core * (alive * 0.9 + pow(e, 3.0) * 0.40);

    vec2 p = uv - 0.5;
    col *= 1.0 - 0.45 * smoothstep(0.30, 0.75, length(p) * 1.4);

    fragColor = vec4(col, 1.0);
}
