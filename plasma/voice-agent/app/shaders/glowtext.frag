// SPDX-License-Identifier: GPL-2.0-or-later
// Status text that glows in the light's colors (docs/67): gold, white and blue running
// across the letters, with a faint warm halo around them.
#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 area;      // px, the text plus its margin
    float time;
};
layout(binding = 1) uniform sampler2D source;

void main()
{
    float a = texture(source, qt_TexCoord0).a;
    vec2 px = 1.0 / area;
    // Three close rings of taps: a smooth halo, not copies of the letters.
    float g = 0.0;
    for (int i = 0; i < 16; i++) {
        float t = float(i) * 0.3926991;
        vec2 dir = vec2(cos(t), sin(t)) * px;
        g += texture(source, qt_TexCoord0 + dir * 2.0).a + 0.75 * texture(source, qt_TexCoord0 + dir * 4.0).a
           + 0.5 * texture(source, qt_TexCoord0 + dir * 6.0).a;
    }
    g = g / 36.0;

    float s = fract(qt_TexCoord0.x * area.x / 160.0 - time * 0.3) * 4.0;
    vec3 gold = vec3(1.0, 0.86, 0.62), blue = vec3(0.62, 0.72, 1.0);
    vec3 grad = mix(gold, vec3(1.0), clamp(s, 0.0, 1.0));
    grad = mix(grad, blue, clamp(s - 1.0, 0.0, 1.0));
    grad = mix(grad, vec3(1.0), clamp(s - 2.0, 0.0, 1.0));
    grad = mix(grad, gold, clamp(s - 3.0, 0.0, 1.0));

    float halo = g * 0.55 * (1.0 - a);
    fragColor = vec4(grad * a + gold * halo, a + halo) * qt_Opacity;
}
