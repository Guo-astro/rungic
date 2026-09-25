// SPDX-License-Identifier: GPL-2.0-or-later
// The light gathered into a capsule near Home (docs/67): the talk control while the
// agent works, answers or waits. Colors turn inside it, a bright core in the middle and
// a soft glow of the same colors around it.
#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 area;      // item size, px (the capsule plus room for its glow)
    vec2 capsule;   // the capsule, px
    float time;
    float glow;     // 0..1
    float bright;   // 0..1
    float light;    // 1 on a light ground: the glow around tints instead of adding light
};

vec3 palette(float t)
{
    // blue, violet, pink, gold, cream, light blue, around.
    t = fract(t) * 6.0;
    vec3 c = mix(vec3(0.36, 0.53, 0.96), vec3(0.55, 0.42, 0.90), clamp(t, 0.0, 1.0));
    c = mix(c, vec3(0.88, 0.49, 0.65), clamp(t - 1.0, 0.0, 1.0));
    c = mix(c, vec3(0.94, 0.76, 0.49), clamp(t - 2.0, 0.0, 1.0));
    c = mix(c, vec3(1.0, 0.94, 0.85), clamp(t - 3.0, 0.0, 1.0));
    c = mix(c, vec3(0.44, 0.63, 1.0), clamp(t - 4.0, 0.0, 1.0));
    return mix(c, vec3(0.36, 0.53, 0.96), clamp(t - 5.0, 0.0, 1.0));
}

void main()
{
    vec2 p = qt_TexCoord0 * area - area * 0.5;
    float r = capsule.y * 0.5;
    vec2 q = abs(p) - vec2(capsule.x * 0.5 - r, 0.0);
    float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;    // < 0 inside

    float turn = atan(p.y, p.x) / 6.2831853;
    vec3 inner = palette(turn + time * 0.12 + length(p) / capsule.x * 0.35);
    vec2 c = p / vec2(capsule.x * 0.32, capsule.y * 0.26);
    inner = mix(inner, vec3(1.0, 0.98, 0.94), exp(-dot(c, c)) * 0.85);
    inner *= 0.5 + 0.5 * bright;
    // A fine light line just inside the edge: glass, not a flat sticker.
    inner += vec3(1.0) * exp(-abs(d + 1.2) / 0.9) * 0.3;

    float inside = 1.0 - smoothstep(-0.8, 0.8, d);
    // Fades out before the item's edge: no box around the glow.
    float room = (area.y - capsule.y) * 0.5;
    float halo = exp(-max(d, 0.0) / (capsule.y * 0.3)) * (1.0 - smoothstep(room * 0.35, room * 0.95, d))
               * glow * (1.0 - inside) * 0.75;
    vec3 glowColor = mix(palette(turn + time * 0.12), pow(palette(turn + time * 0.12), vec3(1.6)), light);
    vec3 around = glowColor * halo;

    vec3 col = inner * inside + around;
    float glowAlpha = mix(max(around.r, max(around.g, around.b)), halo, light);
    float a = clamp(inside + glowAlpha, 0.0, 1.0);
    fragColor = vec4(col, a) * qt_Opacity;
}
