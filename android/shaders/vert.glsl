#version 310 es
// Fullscreen triangle from gl_VertexID — no vertex buffer needed.
// Matches the Plasma/web convention: uv in [0,1], origin bottom-left.
layout(location = 0) out vec2 qt_TexCoord0;

void main() {
    vec2 uv = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    qt_TexCoord0 = uv;
    gl_Position = vec4(uv * 2.0 - 1.0, 0.0, 1.0);
}
