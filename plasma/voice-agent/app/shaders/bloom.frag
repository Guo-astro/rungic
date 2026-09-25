// SPDX-License-Identifier: GPL-2.0-or-later
// The light rising from the Home button while the assistant listens (docs/67): a warm
// halo, colored lights drifting above Home, a white-hot core right over it and a thin
// light along the screen's bottom edge and up its sides. All soft falloffs, no outlines.
#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 area;      // item size, px
    float time;     // s
    float level;    // voice, 0..1 (smoothed)
    float rise;     // 0 gone .. 1 fully up (summon / gathered into the pill)
    float rim;      // edge light, 0..1
    float spread;   // bloom width, px
    float light;    // 1 on a light ground: tinted, deeper colours with ordinary alpha
};

const vec3 BLUE = vec3(0.36, 0.53, 0.96);
const vec3 VIOLET = vec3(0.55, 0.42, 0.90);
const vec3 PINK = vec3(0.88, 0.49, 0.65);
const vec3 GOLD = vec3(0.94, 0.76, 0.49);
const vec3 CREAM = vec3(1.0, 0.94, 0.85);
const vec3 DEEP = vec3(0.18, 0.24, 0.62);

float blob(vec2 p, vec2 c, vec2 r)
{
    vec2 q = (p - c) / r;
    return exp(-dot(q, q));
}

void main()
{
    vec2 p = qt_TexCoord0 * area;
    vec2 home = vec2(area.x * 0.5, area.y);
    float w = spread * (0.7 + 0.3 * rise);
    float h = area.y * rise * (0.5 + 0.34 * level) * (1.0 + 0.03 * sin(time * 1.9));

    vec3 col = vec3(0.0);
    if (h > 1.0) {
        // Halo: warm near Home, cooling to blue at its edge.
        vec2 q = (p - home) / vec2(w * 0.66, h * 0.92);
        float r2 = dot(q, q);
        col += mix(DEEP, GOLD, exp(-r2 * 3.0)) * exp(-r2 * 2.2) * 0.32;

        // Lights drifting above Home, each its own pace: cool on the left, warm on the
        // right, violet higher up, gold low in the middle.
        float t = time;
        vec2 rb = vec2(w * 0.26, h * 0.30);
        col += BLUE * blob(p, home + vec2(-w * 0.30 + sin(t * 0.61) * w * 0.10, -h * (0.30 + 0.08 * sin(t * 0.83))), rb) * 0.5;
        col += vec3(0.44, 0.63, 1.0) * blob(p, home + vec2(-w * 0.46 + sin(t * 0.39 + 3.3) * w * 0.06, -h * 0.16), rb * 0.9) * 0.34;
        col += PINK * blob(p, home + vec2(w * 0.30 + sin(t * 0.73 + 4.2) * w * 0.10, -h * (0.24 + 0.06 * sin(t * 0.97 + 1.0))), rb * 0.95) * 0.46;
        col += VIOLET * blob(p, home + vec2(sin(t * 0.47 + 2.1) * w * 0.22, -h * (0.44 + 0.08 * cos(t * 0.71))), rb * 1.1) * 0.3;
        col += GOLD * blob(p, home + vec2(sin(t * 0.53 + 1.3) * w * 0.10, -h * (0.14 + 0.04 * cos(t * 0.59))), rb * 0.8) * 0.5;

        // White-hot core right over Home, brighter with the voice.
        col += mix(GOLD, CREAM, 0.6) * blob(p, home, vec2(w * 0.2, h * 0.14)) * (0.55 + 0.35 * level);
        // Nothing left at the item's top edge: no line where the light ends.
        col *= smoothstep(0.0, area.y * 0.3, p.y);
    }

    // Edge light: along the bottom (widening from the middle as it comes up), then up the sides.
    float x = p.x / area.x;
    float fromBottom = area.y - p.y;
    float line = exp(-fromBottom / 1.1) + 0.45 * exp(-fromBottom / 7.0);
    vec3 edge = x < 0.5 ? mix(BLUE, CREAM, x * 2.0) : mix(CREAM, PINK, x * 2.0 - 1.0);
    float reach = rise * area.x * 0.62;
    float across = smoothstep(reach + 24.0, reach - 24.0, abs(p.x - home.x));
    col += edge * line * across * mix(0.6, 1.0, 1.0 - abs(x - 0.5) * 2.0) * rim;
    float up = exp(-fromBottom / (area.y * 0.3)) * smoothstep(0.0, area.y * 0.3, p.y) * smoothstep(0.55, 1.0, rise);
    col += BLUE * (exp(-p.x / 1.1) + 0.45 * exp(-p.x / 7.0)) * up * rim;
    col += PINK * (exp(-(area.x - p.x) / 1.1) + 0.45 * exp(-(area.x - p.x) / 7.0)) * up * rim;

    // Dark ground: a soft shoulder instead of clipping; bright stays light, never a flat
    // white patch, and it adds to what is behind.
    vec3 lit = vec3(1.0) - exp(-col * 1.25);
    vec4 onDark = vec4(lit, clamp(max(lit.r, max(lit.g, lit.b)), 0.0, 1.0));
    // Light ground: added light would vanish into white. The same colours, deepened and
    // laid over the ground with their strength as alpha.
    float m = max(col.r, max(col.g, col.b));
    vec3 hue = pow(col / max(m, 1e-4), vec3(1.8)) * 0.92;
    float strength = (1.0 - exp(-m * 1.6)) * 0.85;
    vec4 onLight = vec4(hue * strength, strength);
    fragColor = mix(onDark, onLight, light) * qt_Opacity;
}
