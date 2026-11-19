---
version: "alpha"
name: "GOV.UK Design System"
description: "GOV.UK Design System visual system, translated from the Claude Artisan catalog for use in digital products. Radically clear, task-focused, accessible; Transport/GDS typeface, black on white"
colors:
  primary: "#00703c"
  background: "#ffffff"
  surface: "#f3f2f1"
  text: "#0b0c0c"
  accent: "#1d70b8"
  on-primary: "#FFFFFF"
  on-surface: "#000000"
  on-accent: "#FFFFFF"
typography:
  h1:
    fontFamily: "'GDS Transport', 'Helvetica Neue', Arial, sans-serif"
    fontSize: "4rem"
    fontWeight: "700"
    lineHeight: "1.05"
  body-md:
    fontFamily: "'GDS Transport', 'Helvetica Neue', Arial, sans-serif"
    fontSize: "1rem"
    fontWeight: "400"
    lineHeight: "1.6"
  label-caps:
    fontFamily: "'GDS Transport', 'Helvetica Neue', Arial, sans-serif"
    fontSize: "0.75rem"
    fontWeight: "600"
    letterSpacing: "0.06em"
rounded:
  sm: "0px"
  md: "0px"
  lg: "0px"
spacing:
  sm: "10px"
  md: "20px"
  lg: "40px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    rounded: "{rounded.md}"
    padding: "20px"
  button-secondary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.md}"
    padding: "20px"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.lg}"
    padding: "30px"
  page:
    backgroundColor: "{colors.background}"
    textColor: "{colors.text}"
    padding: "20px"
---
## Overview

GOV.UK Design System visual system, translated from the Claude Artisan catalog for use in digital products. Radically clear, task-focused, accessible; Transport/GDS typeface, black on white

- **Category:** flat-platform
- **Era:** 2012–present
- **Origin:** UK Government Digital Service.
- **Reference:** gov.uk.
- **Structural base:** hero, superfície, conteúdo e grade responsiva

**Defining traits:**
- Radically clear, task-focused, accessible
- Transport/GDS typeface, black on white
- No decoration; content and usability only
- Rigorous WCAG compliance

## Colors

- **bg** — #ffffff
- **surface** — #f3f2f1
- **surface-strong** — #ebeae9
- **border** — #0b0c0c
- **text** — #0b0c0c
- **text-muted** — #505a5f
- **primary** — #00703c
- **accent** — #1d70b8
- **focus** — #ffdd00
- **error** — #d4351c

## Typography

- Display: 'GDS Transport', 'Helvetica Neue', Arial, sans-serif
- Body: 'GDS Transport', 'Helvetica Neue', Arial, sans-serif
- Mono: 'GDS Transport Mono', ui-monospace, monospace

## Layout

- hero, superfície, conteúdo e grade responsiva
- Use a responsive grid and preserve content hierarchy.
- Collapse columns below 768px without horizontal overflow.

## Elevation & Depth

- Radically clear, task-focused, accessible; Transport/GDS typeface, black on white; No decoration; content and usability only; Rigorous WCAG compliance; sombras e elevação

## Shapes

- Radius scale: 0px, 0px, 0px.

## Components

- Buttons keep visible focus and predictable hover/pressed states.
- Cards use the surface and radius scale from the tokens.
- Forms expose persistent labels, textual errors, and keyboard focus.

## Do's and Don'ts

- Do: follow the tokens and the structural composition.
- Do: maintain WCAG AA contrast and `prefers-reduced-motion`.
- Avoid: using the style as decoration without functional hierarchy.

<!-- Source: https://designmd.app/library/govuk-design · designmd.app -->

## Application notes (AgriReach)

AgriReach uses this file as the visual reference for the Streamlit officer review screen.
The GDS Transport typeface is not bundled; the UI uses the listed fallback stack (Helvetica Neue, Arial, sans-serif).
AgriReach is not a GOV.UK product. The style name and vocabulary belong to a third-party platform; this repo follows the tokens only.

Source: https://designmd.app/library/govuk-design
