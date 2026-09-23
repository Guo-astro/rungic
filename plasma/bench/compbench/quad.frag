#version 450
// `taps` extra samples scale per-pixel cost (1 = plain copy, like KWin's window shader).
layout(set = 0, binding = 0) uniform sampler2D tex;
layout(push_constant) uniform Push { vec4 rect; vec4 uv; float alpha; int taps; } pc;
layout(location = 0) in vec2 v_uv;
layout(location = 0) out vec4 color;
void main() {
    vec4 c = texture(tex, v_uv);
    for (int i = 1; i < pc.taps; i++)
        c += texture(tex, v_uv + vec2(float(i) * 0.0007, 0.0));
    c /= float(max(pc.taps, 1));
    color = vec4(c.rgb, c.a * pc.alpha);
}
