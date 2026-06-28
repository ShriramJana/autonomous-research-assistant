# Design System Strategy: The Cognitive Terminal

## 1. Overview & Creative North Star
This design system is built for the high-level researcher—the user who requires extreme clarity, technical precision, and an environment that respects the weight of intellectual labor. 

**Creative North Star: "The Cognitive Terminal"**
Unlike standard consumer interfaces that prioritize "delight" through bouncy feedback, this system prioritizes **intellectual flow**. It is an editorialized version of a quant research terminal. It avoids the "template" look by utilizing intentional asymmetry, varying information density, and a "typography-first" hierarchy. It feels less like an app and more like a high-end instrument.

## 2. Colors & Surface Architecture
The color philosophy is rooted in "Ink & Obsidian." We use a monochromatic foundation to reduce cognitive load, using our muted electric blue (`primary`) only for critical path actions and status indicators.

### The "No-Line" Rule
To achieve a premium, custom feel, designers are strictly prohibited from using 1px solid borders to section off major layout areas. Instead, boundaries must be defined by **background color shifts**. 
- Use `surface-container-low` for secondary panels.
- Use `surface-container-lowest` for the primary work area.
- Boundaries are felt through the transition of tones, not the presence of lines.

### Surface Hierarchy & Nesting
Depth is achieved through "Tonal Stacking." Imagine the UI as sheets of dark, matte glass layered atop one another. 
- **Base Level:** `surface` (#131313)
- **Secondary Workspaces:** `surface-container-low` (#1c1b1b)
- **Active Modals/Overlays:** `surface-container-highest` (#353534)

### Signature Textures (Subtle Sophistication)
While the user requested "no gradients," we implement **"Micro-Gradients"** to avoid a flat, dead look. Main CTAs should utilize a 1-degree linear gradient from `primary` (#b5c4ff) to `primary_container` (#638aff). This is not for "flair," but to provide a tactile sense of depth that a flat fill cannot achieve.

## 3. Typography: Editorial Precision
The system uses a dual-font approach to separate **Narrative** from **Data**.

- **Geist Sans (Body/Headlines):** Used for prose, system navigation, and instructions. It is the "human" element of the assistant.
- **Geist Mono (Metadata/Citations/Stats):** Used for everything technical. Citations, line numbers, timestamps, and LaTeX-style data must be in Mono. This signals to the user that this information is "raw" and "verifiable."

**The Hierarchy:**
- **Display (3.5rem):** Use for entry states with generous whitespace.
- **Label-sm (0.6875rem):** Always Geist Mono. Uppercase with 0.05em tracking for a "terminal" aesthetic.

## 4. Elevation & Depth: Tonal Layering
Traditional drop shadows are forbidden. They feel "web-standard" and cheap. We use **Ambient Depth**.

- **The Layering Principle:** Place a `surface-container-low` card on a `surface` background. The shift in hex value is the only "elevation" needed.
- **Ambient Shadows:** For floating elements (like command palettes), use a 24px blur with 4% opacity, using the `on_surface` color as the shadow tint. This mimics natural light rather than a digital drop shadow.
- **The "Ghost Border":** If a container requires a border for accessibility, use the `outline_variant` (#434654) at **20% opacity**. This creates a "suggestion" of a container without breaking the visual flow.
- **Glassmorphism:** Floating toolbars must use `surface_container` with a `backdrop-filter: blur(12px)`. This integrates the UI into the data behind it.

## 5. Components

### Buttons
- **Primary:** Gradient fill (Primary to Primary-Container), white text. `rounded-md` (0.375rem).
- **Secondary:** Ghost style. No background, 20% opacity `outline-variant` border.
- **Tertiary:** Pure text in `Geist Mono`, all caps, for low-priority actions like "CANCEL" or "RESET."

### Input Fields
- Avoid full-box borders. Use a `surface-container-high` background with a 1px `outline-variant` bottom border.
- **Focus State:** The bottom border transitions to `primary` (#b5c4ff). No "glow" or "outer ring" animations.

### Information Density & Lists
- **The Research View:** In high-density views, use `body-sm` (0.75rem) and `label-sm` to pack data. 
- **Forbid Dividers:** Do not use `<hr />` tags. Separate list items using `12px` of vertical whitespace or a 2% shift in background color on hover.

### Progress & Status
- **Pulse Indicators:** Status indicators use a soft pulse of `primary` (#b5c4ff). Avoid "bouncy" or "playful" loading spinners; use a linear, horizontal progress bar that fills with a precision-weighted speed.

## 6. Do's and Don'ts

### Do
- **Embrace Asymmetry:** Align technical data to the right and narrative text to the left to create a "split-brain" terminal layout.
- **Use "Data-Heavy" Labels:** Instead of just "Date," use `[TIMESTAMP_UTC_04]`. It reinforces the technical nature of the system.
- **Protect Whitespace:** On initial entry (the "Ask" state), maintain 40% screen-center whitespace.

### Don't
- **No Rounded-Full:** Avoid pill-shaped buttons. Use the `md` (0.375rem) scale for everything to maintain a "structured" look.
- **No Decorative Icons:** Icons must be functional (e.g., "Download," "Copy"). Avoid "Robot" heads or "Magic Sparkles." If an icon doesn't serve a utility, remove it.
- **No Pure Black:** Never use #000000. Use `surface` (#131313) to ensure that "Ghost Borders" and "Ambient Shadows" remain visible.