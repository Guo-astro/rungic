#version 450
// One textured quad per draw; rect/uv in push constants (triangle strip, 4 vertices).
layout(push_constant) uniform Push { vec4 rect; vec4 uv; float alpha; int taps; } pc;
layout(location = 0) out vec2 v_uv;
void main() {
    vec2 p = vec2(float(gl_VertexIndex & 1), float((gl_VertexIndex >> 1) & 1));
    v_uv = pc.uv.xy + p * pc.uv.zw;
    gl_Position = vec4(pc.rect.xy + p * pc.rect.zw, 0.0, 1.0);
}
