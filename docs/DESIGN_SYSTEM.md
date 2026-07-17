# Vitals Design System

> **Quiet Precision** is the single visual language for Vitals. It should feel
> calm, exact and personal: a private health workspace, not an admin panel and
> not a motivational fitness app.

## Product character

Vitals is a decision-support surface for one person with a long health history.
The interface therefore optimizes for comprehension, trust and calm repetition.

Three rules govern every screen:

1. **Answer before controls.** Show the current state or useful interpretation
   before forms, configuration and historical detail.
2. **Hierarchy before decoration.** Space, type and rules create structure.
   Surfaces are used only when they clarify a distinct object or action.
3. **Density with breathing room.** Preserve the full dataset, but reveal dense
   detail progressively and keep primary scans short.

The brand should read as warm near-black, mineral neutrals and restrained
champagne. Semantic green, blue, amber and red communicate health state; they
never compete with the brand accent.

## Source of truth

The interface is layered in this order:

1. `tailwind.css` — compiled utilities used by existing templates.
2. `vitals.css` — structural compatibility and component primitives.
3. `vitals-masthead.css` — shell compatibility.
4. `vitals-design.css` — canonical tokens, shell and shared components.
5. Narrow page layers such as `vitals-data.css`, `vitals-product.css` and
   `vitals-settings.css`.

New visual work belongs in the canonical foundation or a narrowly scoped page
layer. Do not add another theme, mode or parallel component system.

## Tokens

Use the CSS custom properties from `vitals-design.css`; never copy their hex
values into page styles.

### Color

| Role | Token | Intended use |
| --- | --- | --- |
| Canvas | `--bg` | Main application background |
| Inset canvas | `--bg-inset` | Recessed controls and compact detail |
| Surface | `--surface` | A distinct object or working area |
| Raised surface | `--surface-2` | Hover, selected and nested control state |
| Strong surface | `--surface-3` | Rare emphasis |
| Primary text | `--fg` | Titles and important values |
| Secondary text | `--fg-2` | Body copy |
| Muted text | `--muted` | Labels and supporting metadata |
| Faint text | `--faint` | Tertiary metadata only |
| Brand action | `--accent` | Primary action and active navigation |
| Positive | `--good` | Healthy or completed state |
| Negative | `--bad` | Risk, destructive action or failure |
| Warning | `--warn` | Attention without alarm |
| Informational | `--cool` | Neutral health information |

Champagne is scarce by design. If everything is accented, nothing is primary.
Do not use translucent glass, decorative gradients or purple as a generic card
color.

### Typography

- `--font-display`: Bricolage Grotesque, then Outfit. Use for page titles,
  meaningful section headings and large metrics.
- `--font-body`: Inter. Use for body copy, controls, tables and metadata.
- Numeric data uses tabular figures through `.tnum`, `.v-num` or `.font-mono`.

Use the shared scale:

- `--text-title` for the page title.
- `--text-metric` for one primary measurement.
- `--text-heading` for a section heading.
- `--text-card` for a compact object title.
- `--text-body`, `--text-label` and `--text-micro` for supporting content.

Avoid oversized display copy inside the application. A title should orient the
user without pushing the useful state below the fold.

### Space, radius and depth

Spacing uses `--space-1` through `--space-12`. Prefer a clear 8 px rhythm and
use 4 px only for tightly related label/value pairs.

- `--radius-sm`: controls and compact tags.
- `--radius`: standard surfaces.
- `--radius-lg`: major working areas.
- `--radius-pill`: statuses and segmented controls only.

Shadows are quiet and rare. Borders and contrast should establish most depth.
Never stack multiple decorated cards just to create spacing.

## Application shell

Desktop uses one persistent left sidebar with three labeled groups. The active
destination uses `aria-current="page"`. Content lives in `#main-content`, and a
skip link is the first focusable element.

At medium widths the sidebar becomes compact. On mobile it is replaced by an
opaque bottom navigation and an accessible drawer. The drawer is a modal dialog,
has a visible close action and never relies on blur to separate itself from the
page.

The shell owns navigation only. Page-specific secondary navigation belongs in
the content column and should usually be sticky or horizontally scrollable on
small screens.

## Page anatomy

A strong Vitals page normally follows this order:

1. **State header** — destination, date/range and one concise explanation.
2. **Primary answer** — current metric, executive brief or immediate status.
3. **Relevant action** — log, import, generate or edit.
4. **Trend and context** — charts, interpretation and comparisons.
5. **History or configuration** — dense tables, lists and advanced controls.

Not every page needs a card at every level. Sections can be separated by space
and a one-pixel rule. Use a surface when the content is an object that can be
acted on, selected or understood independently.

## Core patterns

### Health metrics

Lead with the current value, unit, timestamp and change. A chart must include a
human-readable interpretation or a clear reason for being present. Range and
source controls sit close to the chart, not in a detached toolbar.

### Protocols and routines

Organize supplements, skincare and medication around the moment of use. Show
today's active protocol first; catalog management and history come later.

### Long records

Tables remain tables on large screens. On narrow screens either expose the most
important columns in a stacked row or place the table in an explicitly
scrollable region with a visible cue. The document itself must never overflow
horizontally.

### Progressive disclosure

Use native `details`/`summary` for workout sets, interaction explanations and
other repeated dense records. Summaries must still communicate the important
state when closed. Do not hide a primary action behind disclosure.

### Empty, loading and error states

An empty state explains what data is absent and offers one useful next action.
Loading uses stable skeletons or a compact status; it must not shift the page
dramatically. Errors explain what the user can do next and preserve entered
form data whenever possible.

### Forms and dialogs

- Every input has a visible label; placeholders are examples, not labels.
- Touch targets are at least 44 by 44 CSS pixels.
- Destructive actions are visually secondary until confirmation.
- A dialog uses `role="dialog"`, `aria-modal="true"`, an accessible title and a
  labeled close action.
- Primary actions contain an active verb: Save, Add, Import, Generate.

## Charts

Chart.js reads the resolved CSS tokens through `window.vitalsChartTheme()`.
Charts use restrained lines, faint grid rules and direct labels where practical.
Avoid rainbow series. Start with champagne for the principal series, then use
semantic colors only when they carry meaning.

Tooltips must be opaque, high-contrast and keyboard-independent information
must also be available in nearby text or labels. Canvas containers need a stable
height on every breakpoint.

## Responsive behavior

Design for content, then verify at these pressure points:

- 1440 px desktop: persistent sidebar, generous but bounded content width.
- 1024 px compact desktop/tablet: compact navigation and preserved hierarchy.
- 390 px phone: one primary column, opaque mobile navigation, safe-area padding.
- 320 px narrow phone: no document overflow and no clipped actions.

Use `minmax(0, 1fr)` for fluid grid tracks and `min-width: 0` on grid/flex
children that contain data. Page layers must include a mobile strategy, not just
a desktop grid.

## Accessibility

These are release requirements:

- Visible `:focus-visible` treatment on every interactive element.
- WCAG AA contrast for text and controls.
- Semantic landmarks, headings and native controls first.
- `aria-current` for the active destination and `aria-expanded` for disclosure.
- Reduced motion via `prefers-reduced-motion: reduce`.
- Safe-area support for the mobile bottom navigation.
- No information communicated by color alone.
- No `outline: none` unless a stronger visible focus style replaces it.

Animation is limited to short state transitions. Never use `transition: all`,
and never animate layout continuously in a data-heavy screen.

## Voice and labels

Vitals is a navigator, not a judge. Labels are calm, factual and specific.
Prefer “No sleep data for this date” over “You failed to sync sleep.” Avoid
gamification, guilt and congratulatory copy that is not supported by the data.

Russian and English strings belong in `vitals/i18n.py`. Template-only prose is
acceptable only when a page is intentionally single-language; new shared shell
copy must always be translated.

## Release checklist

Before shipping a visual change:

- Confirm it uses the existing shell and token set.
- Confirm the primary answer appears before configuration.
- Verify no decorative gradient, glass surface, emoji icon or nested card stack
  was introduced.
- Verify keyboard focus, labels, dialog semantics and 44 px targets.
- Verify 1440 px and 390 px in a real browser.
- Check document width against viewport width on every touched page.
- Check the browser console and exercise Alpine, HTMX and form behavior.
- Run the relevant design contracts and the complete test suite.
- Rebuild `tailwind.css` only when template utility classes require it.

Quiet Precision succeeds when the interface disappears behind the health story:
the user sees what changed, why it matters and what can be done next.
