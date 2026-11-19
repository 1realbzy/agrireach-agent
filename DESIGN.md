---
version: "alpha"
name: "Nature Distilled"
description: "Design with nature distilled aesthetic. Ideal for landing pages, saas. AI-ready template."
colors:
  primary: "#C67B5C"
  secondary: "#D4C4A8"
  tertiary: "#B5651D"
  neutral: "#F5F0E1"
  surface: "#8B4513"
  accent: "#6B7B3C"
typography:
  h1:
    fontFamily: System UI stack
    fontSize: 2.25rem
    fontWeight: 700
  body-md:
    fontFamily: System UI stack
    fontSize: 1rem
    fontWeight: 400
  label-caps:
    fontFamily: System UI stack
    fontSize: 0.75rem
    fontWeight: 500
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.neutral}"
    padding: 12px
---

## Overview

Design with nature distilled aesthetic. Ideal for landing pages, saas. AI-ready template. The cold blue-white interfaces of the 2010s had a good run. Then everyone got tired of living inside a hospital. Around 2020, Japandi — that unlikely marriage of Japanese wabi-sabi and Scandinavian restraint — started bleeding from interiors into digital. Designers noticed: you could strip things back without stripping out soul. Muted ochres, warm greys, linen textures. Suddenly screens felt like rooms you'd actually want to sit in.

Post-pandemic, the shift accelerated. People craved warmth, tactility, evidence of human hands. Swiss grid discipline didn't disappear — it just learned to breathe. Typefaces got softer serifs. Whitespace turned to warm-space. The palette moved from silicon to skin, from steel to terracotta. Nature wasn't decoration anymore; it was the foundation.

By 2025, warm minimalism isn't a trend — it's a correction. We over-indexed on cold precision for a decade. Now the best work proves you can be rigorous and gentle simultaneously. Grid-tight, but alive.

- Density: 3/10 — Airy
- Variance: 8/10 — Expressive
- Motion: 8/10 — Cinematic

- **Style:** Natural, Distilled, Warm, Handmade
- **Keywords:** Muted earthy, skin tones, wood, soil, sand, terracotta, warmth, organic materials, handmade warmth
- **Era:** 2025+ Handmade Warmth
- **Light/Dark:** ✓ Full / ◐ Partial

## Colors

- **Terracotta** (#C67B5C) — Primary surface or dominant color
- **Sand Beige** (#D4C4A8) — Secondary surface or text color
- **Warm Clay** (#B5651D) — Supporting palette color
- **Soft Cream** (#F5F0E1) — Light surface, card backgrounds
- **Earth Brown** (#8B4513) — Extended palette, decorative use
- **Olive Green** (#6B7B3C) — Success states, positive indicators
- **Warm Stone** (#9C8B7A) — Extended palette, decorative use


## Typography

- **Display / Hero:** System UI stack (-apple-system, sans-serif) — Weight 700, tight tracking, used for headline impact
- **Body:** System UI stack (-apple-system, sans-serif) — Weight 400, 16px/1.6 line-height, max 72ch per line
- **UI Labels / Captions:** System UI stack (-apple-system, sans-serif) — 0.875rem, weight 500, slight letter-spacing
- **Monospace:** JetBrains Mono — Used for code, metadata, and technical values

Scale:
- Hero: clamp(2.5rem, 5vw, 4rem)
- H1: 2.25rem
- H2: 1.5rem
- Body: 1rem / 1.6
- Small: 0.875rem


## Layout

- **Grid:** CSS Grid primary. Max-width containment: 1280px centered with 1.5rem side padding.
- **Spacing rhythm:** Balanced. Base unit: 0.5rem (8px).
- **Section vertical gaps:** clamp(4rem, 8vw, 8rem).
- **Hero layout:** Asymmetric composition.
- **Feature sections:** Asymmetric grid with varied card sizes. No 3-equal-columns.
- **Mobile collapse:** All multi-column layouts collapse below 768px. No horizontal overflow.
- **z-index contract:** base (0) / sticky-nav (100) / overlay (200) / modal (300) / toast (500).


## Elevation & Depth

Subtle parallax, natural easing (ease-out), texture overlays, grain effects, soft shadows

- **Physics:** Spring — stiffness 120, damping 20. Confident, weighted transitions.
- **Entry animations:** Fade + translate-Y (16px → 0) over 540ms ease-out. Staggered cascades for lists: 120ms between items.
- **Hover states:** Scale(1.03) + shadow lift over 200ms.
- **Page transitions:** Fade + slide (300ms).
- **Performance:** Only transform and opacity animated. No layout-triggering properties.


## Shapes

Base corner radius: 8px. See rounded tokens in front matter for the full scale.


## Components

- **Primary Button:** Rounded (organic (varied)) shape. Accent color fill. Hover: 8% darken + subtle lift shadow. Active: -1px translate tactile press. Font weight 600. No outer glows.
- **Secondary / Ghost Button:** Outline variant. 1.5px border in muted color. Text in primary color. Hover: subtle background fill.
- **Cards:** Rounded (organic (varied)) corners. Surface background. Subtle shadow (0 2px 12px rgba(0,0,0,0.06)). 1px border stroke.
- **Inputs:** Label above input. 1px border stroke. Focus ring: 2px accent color offset 2px. Error text below in semantic red. No floating labels.
- **Navigation:** Primary surface background. Active item: accent color indicator. Font weight 500 when active.
- **Skeletons:** Shimmer animation matching component dimensions. No circular spinners.
- **Empty States:** Icon-based composition with descriptive text and action button.


## Do's and Don'ts

- No emojis in UI — use icon system only (Lucide, Heroicons)
- No pure black (#000000) — use off-black or charcoal variants
- No oversaturated accent colors (saturation cap: 80%)
- No 3-column equal-width feature layouts — use zig-zag or asymmetric grid
- No `h-screen` — use `min-h-[100dvh]`
- No AI copywriting clichés: "Elevate", "Seamless", "Unleash", "Next-Gen"
- No broken external image links — use picsum.photos or inline SVG
- No generic lorem ipsum in demos

- Do Earth tones dominant
- Do Warm feel achieved
- Do Textures subtle
- Do Handmade quality
- Do Sustainable messaging
- Do Calming aesthetic


## Use Case

Landing pages, SaaS

<!-- Source: https://designmd.app/library/nature-distilled · designmd.app -->

## AgriReach adaptation

The officer review screen uses Nature Distilled as the visual source, adapted for a recorded agricultural-advisory tool that must stay high-contrast and readable.

Adaptations (not in the catalog file above):

- **Background** stays Soft Cream (`#F5F0E1`); **cards** use a slightly lighter warm paper (`#FFF9F0`).
- **Primary / leaf green** is darkened to Forest Leaf (`#2D5A27`) so white button text meets WCAG AA. Olive (`#6B7B3C`) remains a success tint, not the only text colour.
- **Body text** is dark earth (`#2C2118`), not pure black, and not Sand Beige (too light for body copy).
- **Soil brown** (`#6B3E24`) is used for borders and labels; **terracotta** (`#C67B5C`) is reserved for the Auto-released badge and accents (the catalog 10% highlight).
- **Radius** is 12px on cards and 8px on buttons, with a soft shadow `0 2px 12px rgba(44, 33, 24, 0.08)`.
- **Focus** is a 3px gold ring (`#E0A84A`) with a 2px offset, so keyboard focus stays obvious on cream and green.
- Type uses the listed system-ui / humanist sans stack. No extra webfonts are loaded.

These tokens are applied in `.streamlit/config.toml` and `src/agrireach/ui.py`.

Source: https://designmd.app/library/nature-distilled
