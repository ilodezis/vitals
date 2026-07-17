# Vitals — Design System

> **Scope note:** Vitals ships two interface shells that read from the *same* token
> layer — `classic` (default) and `masthead` (opt-in, toggled per-user in
> Settings → Interface, see [`ui_version_service.py`](../vitals/services/ui_version_service.py)).
> This document canonizes **Masthead** as the reference visual language: it's
> what new screens should be designed against. Classic is documented where it
> still differs, but treat it as legacy — don't invest new visual design in
> classic-only patterns.
>
> Grounded entirely in the current implementation — every token and class below
> exists in [`web/static/vitals.css`](../web/static/vitals.css) and
> [`web/static/vitals-masthead.css`](../web/static/vitals-masthead.css) at the time
> of writing (2026-07-17). If you change a token, update this file in the same PR.

## At a glance

- **Warm health companion, not a clinical terminal.** Dim plum-charcoal, never
  pure black, never white.
- **One accent, spent on purpose.** Amber (`--accent`) is reserved for wayfinding
  (the active nav item) and the page's single primary CTA — not for data values,
  not for decoration. Everything else stays neutral so those signals keep meaning.
- **No monospace, anywhere.** Numbers use Inter with `tabular-nums`; columns still
  align.
- **Six type sizes. No others.** `--text-title` → `--text-micro`; don't reach for
  an arbitrary `text-[17px]`.
- **A ladder, not a wall of red.** System alerts are `info` / `warn` / `block` —
  calm by default, loud only when a save must actually be stopped.

## Table of contents

1. [Principles](#1-principles)
2. [Foundations](#2-foundations)
3. [Layout & shell](#3-layout--shell)
4. [Components](#4-components)
5. [Patterns](#5-patterns)
6. [Accessibility](#6-accessibility)
7. [Governance — extending the system](#7-governance--extending-the-system)

---

## 1. Principles

These aren't aspirational — each one is a direct, enforced constraint in the CSS
today, and the reasoning is worth carrying into every new screen:

1. **Navigator, not overseer.** Vitals surfaces data and lets the owner decide;
   it doesn't nag. That's why validation is a three-step ladder (info/warn/block)
   instead of red everywhere, and why the tone throughout is "here's what's
   happening," not "you did something wrong."
2. **Warm and dim, deliberately not two other things.** Not the near-black /
   electric-accent "AI dashboard" look (tried, rejected), and not a bright/white
   clinical UI. Plum-charcoal surfaces with a single honey-amber accent.
3. **Amber is scarce on purpose.** At rest, amber appears in exactly three kinds
   of places: the *active nav indicator* (top-nav link, masthead rail icon, or
   masthead tab underline — all the same "you are here" signal), the page's
   *one primary CTA*, and small *brand/live chrome* (logo pulse, brand dot) that
   isn't data. Metric values, chips, tags, filter pills and section markers all
   stay neutral — see the repeated `.v-metric-value`, `.v-chip`, `.v-tag`,
   `.v-pill`, `.v-bar` comments in `vitals.css` that spell this out. If you're
   about to add a new amber element, ask whether it's actually one of those
   three things — if not, it should be neutral.
4. **No monospace, full stop.** A hard owner constraint. `.font-mono`/`.tnum`
   are aliased back to Inter + `tabular-nums` so number columns still line up
   without a mono typeface anywhere in the product.
5. **A closed type scale.** Six sizes cover every heading, label and value in
   the app. Adding a seventh should be rare enough to need a reason.
6. **Editorial over "boxes of boxes."** Masthead's header (eyebrow → tabs → big
   title → key figures) reads like a magazine section opener, not a SaaS KPI
   dashboard. Prefer that hierarchy to another grid of stat cards.

## 2. Foundations

### 2.1 Color

All colors are CSS custom properties defined once, in `:root`, in
[`vitals.css`](../web/static/vitals.css). Templates and component classes
consume them via `var(--token)` — never a hardcoded hex.

**Surfaces** (layered page → card → raised)

| Token | Value | Use |
|---|---|---|
| `--bg` | `#1D1A21` | Page background |
| `--bg-inset` | `#151318` | Recessed wells — inputs, table heads, dropdown triggers |
| `--surface` | `#332F3C` | Cards — the default "lifted" surface |
| `--surface-2` | `#3D3848` | Hover states, active segmented-control pill, raised rows |
| `--surface-3` | `#46404F` | Chips sitting on top of a card |
| `--line` | `#443E4F` | Hairline borders |
| `--line-2` | `#564E63` | Stronger borders (ghost-button outline, switch track) |

**Text**

| Token | Value | Use |
|---|---|---|
| `--fg` | `#F3F0F6` | Primary text |
| `--fg-2` | `#CFC8D8` | Secondary text |
| `--muted` | `#A39AB0` | Labels, muted values |
| `--faint` | `#8C829C` | Placeholders, faint/tertiary text |

**Accent — honey-amber**

| Token | Value | Use |
|---|---|---|
| `--accent` | `#F5A623` | The one accent. Primary CTA fill, active-state color. |
| `--accent-2` | `#FFC25A` | Hover state, active-state icon/text tint |
| `--accent-ink` | `#2A1B03` | Text/icon color **on top of** `--accent` — never put light text on amber |
| `--accent-soft` | `rgba(245,166,35,.13)` | Tinted background for active/hover chrome |
| `--accent-line` | `rgba(245,166,35,.34)` | Tinted border, focus rings |

**Semantic**

| Token | Value | Use |
|---|---|---|
| `--good` / `--good-soft` | `#6FC58E` / `rgba(111,197,142,.13)` | Positive tone on a metric or chip |
| `--bad` / `--bad-soft` | `#E87056` / `rgba(232,112,86,.13)` | Negative tone; also the `block` alert color |
| `--bad-strong` | `#FF8469` | Critical / out-of-range emphasis |
| `--warn` / `--warn-soft` | `#F0B24A` / `rgba(240,178,74,.13)` | The `warn` alert tier |
| `--cool` / `--cool-soft` | `#6FB6C9` / `rgba(111,182,201,.13)` | Temporal/category tag — "day" side of a day/night pairing |
| `--violet` / `--violet-soft` | `#B093D6` / `rgba(176,147,214,.13)` | Temporal/category tag — "evening/night" side |

`.good`/`.bad` are **direction-agnostic** — the page decides which way is good.
On the Weight page, for instance, a negative weekly slope (losing weight) maps
to `good` and a positive one to `bad`; the token pair itself carries no
assumption about which sign is desirable.

> **Tailwind note:** `tailwind.config.js` remaps Tailwind's `slate` and `teal`
> scales onto this same palette (`slate` → plum-charcoal, `teal` → honey-amber)
> so legacy utility-class markup (`bg-slate-800`, `text-teal-500`, …) inherits
> the theme automatically. That remap is a compatibility shim for old markup —
> **new markup should reach for `.v-*` classes or `var(--token)`, not raw
> Tailwind color utilities.**

### 2.2 Typography

Three families, self-hosted as woff2 under `web/static/fonts/` and loaded via
`web/static/fonts.css` (linked from `base.html` and `oauth_authorize.html` —
no Google Fonts CDN dependency):

| Family | Weights loaded | Role |
|---|---|---|
| **Inter** | 400–800 | Body text, UI chrome, all numbers (via `tabular-nums`) |
| **Outfit** | 400–900 | Headings, card titles, classic KPI metric values — the "display sans" |
| **Bricolage Grotesque** | 600–800 | Masthead-only: big editorial titles and tab labels (`--mh-display`) |

No monospace typeface is loaded or used. `.font-mono` / `.tnum` force Inter with
`font-variant-numeric: tabular-nums` and `cv01`/`ss01` feature settings, so
number-heavy tables still align in columns.

**Core scale** (six sizes, defined as tokens, shrink slightly ≤640px):

| Token | Desktop | ≤640px | Use |
|---|---|---|---|
| `--text-title` | 26px | 22px | Page hero `<h1>` |
| `--text-metric` | 28px | 24px | Big numbers in stat cards |
| `--text-heading` | 18px | 16px | Section headings |
| `--text-card` | 15px | 14px | Card titles |
| `--text-body` | 14px | 14px | Table values, body copy |
| `--text-label` | 13px | 13px | Labels, column headers (muted) |
| `--text-micro` | 12px | 12px | Units, dates, secondary info (muted) |

**Masthead display type** (layered on top of the core scale, `.mh-*` classes):

| Class | Spec | Use |
|---|---|---|
| `.mh-eyebrow` | 11px/600, uppercase, `.14em` tracking, `--faint` | Section-number eyebrow row |
| `.mh-tab` | 14px/500 display font → 600/`--fg` + amber underline when active | In-rubric section switcher |
| `.mh-title` | 62px/800 display font, 1.05 line-height → 38px on mobile | The big editorial `<h1>` |
| `.mh-metric-value.is-primary` | 50px/700 display font → 38px on mobile | The one "hero" key figure |
| `.mh-metric-value` | 21px/600 Inter, tabular-nums | Secondary key figures |
| `.mh-metric-label` | 11px/600, uppercase, `.1em` tracking, `--faint` | Key-figure caption |

### 2.3 Spacing & radius

4px-base spacing scale:

| Token | Value |
|---|---|
| `--space-1` … `--space-12` | 4 / 8 / 12 / 16 / 24 / 32 / 48px |

Radius scale, applied by role rather than by component:

| Token | Value | Typical use |
|---|---|---|
| `--radius-sm` | 10px | Icon buttons, chips, dropdown options |
| `--radius` | 14px | Buttons, inputs, alerts, `.v-card-inset` |
| `--radius-lg` | 20px | Cards, modals, metric tiles |
| `--radius-pill` | 999px | Switch track, filter-pill shapes |

### 2.4 Elevation

Two shadow tokens only:

- `--shadow` — `0 1px 2px rgba(0,0,0,.25), 0 12px 30px -16px rgba(0,0,0,.55)` —
  default card lift. Paired with a `inset 0 1px 0 rgba(255,255,255,.05)`
  top-highlight on cards/metrics for a subtle bevel.
- `--shadow-lg` — `0 24px 60px -22px rgba(0,0,0,.7)` — modals and floating
  dropdown panels, i.e. anything above the card layer.

### 2.5 Iconography

Every icon in the product follows one contract: 24×24 viewBox, Heroicons-outline
style —

```html
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
  <path stroke-linecap="round" stroke-linejoin="round" d="…" />
</svg>
```

Color always comes from `currentColor` (inherits text color / token), never a
hardcoded fill. Rendered size varies by context: 18px in the masthead rail,
~15px inline next to nav labels, ~20–32px in headers and empty states.

### 2.6 Motion

- **Micro-interactions:** 120–200ms `ease` on color/background/border/shadow
  (hover, focus, press). Buttons add a 1px `translateY` press on `:active`;
  `.v-card-tile` lifts 2px on hover.
- **Page navigation:** the View Transitions API (90ms fade-out / 210ms fade-in)
  with an htmx opacity-swap fallback (~150–200ms) for browsers without it.
- **Ambient/brand only:** the masthead logo pulse (2.6s) and classic header's
  brand-icon glow (2.5s) are the only looping animations — reserved for "this is
  alive" chrome, not for data or content.
- **`prefers-reduced-motion: reduce`** collapses all animation/transition
  durations to ~0 globally. Any new animation must respect this for free by
  using standard `transition`/`animation` properties rather than JS-driven motion.

## 3. Layout & shell

### 3.1 Masthead (canonical)

**Desktop (≥768px):** a fixed 76px icon-rail (`--mh-rail-w`, class `.mh-rail`)
on the left: pulsing brand mark → divider → one icon button per enabled section
→ spacer → settings + avatar. The rail's contents, the in-content tab row, and
the "section N of rubric" numbering all derive from **one registry** —
`MH_RUBRICS` / `MH_SECTIONS` in
[`partials/masthead.html`](../web/templates/partials/masthead.html) — so the
rail and the tabs never drift apart. Sections are grouped into three rubrics:
Health (weight, garmin, hevy, nutrition, reports, charts), Markers (glp1, labs,
genetics), Lifestyle (supplements, skincare, interactions); membership is
gated by `enabled_modules`.

**Mobile (<768px):** the rail is replaced by a 52px `.mh-topbar` — brand
wordmark + a hamburger "menu" trigger.

**Section header**, rendered by the `masthead_header(section, title, metrics)`
macro at the top of every module page:

```html
{% from "partials/masthead.html" import masthead_header with context %}
{{ masthead_header('weight', t('nav.weight'), [
    {'label': t('weight.latest'), 'unit': t('common.kg'), 'primary': true, 'value': …},
    {'label': t('weight.weekly_change'), 'unit': t('common.kg'),
     'tone': 'good' if trend.slope_per_week < 0 else 'bad', 'value': …},
]) }}
```

renders eyebrow (`Section 01 · Health`) → optional right-aligned actions
(pass via `{% call %}`) → underline tabs for sibling sections in the same
rubric → the big `<h1>` → an inline key-figures row (`.mh-metrics`,
divider-separated, one figure flagged `primary` in display type). This row
**replaces** the classic KPI-card grid — don't build both.

A metric dict may also carry `href`: that entry renders as `<a class="mh-metric">`
instead of `<div>`, for a key figure that should double as a shortcut (e.g.
Garmin's Sleep figure linking straight to the latest night's detail page).
Omit it and you get the plain non-interactive tile, same as before.

### 3.2 Classic (legacy default)

A blurred-glass top `.v-header` navbar (4rem tall, active link picks up the
amber wayfinding treatment) plus a `.v-metric` KPI-card grid where Masthead
would use the inline key-figures row. Same tokens and same components below
the fold — only the top-of-page frame differs. `ui_version` defaults to
`"classic"` (see [`ui_version_service.py`](../vitals/services/ui_version_service.py));
it's the safe fallback, not the design target.

### 3.3 Responsive & PWA plumbing

- Breakpoints actually in use: **480 / 640 / 768px.**
- Below 768px, inputs are forced to 16px font (`.v-input`/`.v-select`/`.v-textarea`)
  to stop iOS Safari's auto-zoom-on-focus; interactive elements grow to ≥44px
  touch targets (buttons, segmented control, filter pills, icon buttons).
- Safe-area insets (`env(safe-area-inset-*)`) are cached into `--sat`/`--sab`/
  `--sal`/`--sar` by a small viewport-sync script in `base.html`, because iOS
  standalone-PWA mode resolves `env()`/`dvh` unreliably on cold start. Use
  `max(env(safe-area-inset-top), var(--sat, 0px))` — don't assume `env()` alone
  is populated on first paint.
- `.v-app-shell` sizes to `var(--app-height, 100dvh)` for the same reason —
  never hardcode `100vh` for the app frame.
- The bottom nav (`.v-bottom-nav`) is an in-flow flex child, deliberately
  **not** `position: fixed` — fixed positioning was found to drift in iOS PWA
  mode when the body has `overflow: hidden`.

## 4. Components

Reference for the `.v-*` component classes in `vitals.css`. These are shared by
both interfaces — build with these before reaching for raw Tailwind utilities.

### Buttons

| Class | Look | Use |
|---|---|---|
| `.v-btn` | Solid amber, `--accent-ink` text, glow shadow | The page's **one** primary CTA |
| `.v-btn-ghost` | Transparent, `--line-2` border → amber-tinted on hover | Secondary actions, modal "Cancel" |
| `.v-btn-danger` | Solid `--bad`, dark text | Destructive confirms (e.g. override) |
| `.v-icon-btn` | 32px square, muted → accent-2 on hover; `.danger` variant → `--bad` | Row-level edit/delete/archive |

### Cards

| Class | Look | Use |
|---|---|---|
| `.v-card` | `--surface` + border + `--radius-lg` + shadow + top highlight | Default content container |
| `.v-card-flat` | Same, no shadow | Quiet/nested contexts |
| `.v-card-inset` | `--bg-inset`, `--radius` | Recessed "well" sub-panels |
| `.v-card-tile` | `--bg-inset`, lifts + amber-line border on hover | Clickable grid tiles |

### Metrics / key figures

Classic uses a KPI grid of `.v-metric` tiles:

```html
<div class="v-metric">
  <span class="v-metric-label">{{ t("weight.latest") }}</span>
  <div class="flex items-baseline">
    <span class="v-metric-value">{{ weights[0].weight_kg | format_number }}</span>
    <span class="v-metric-unit">{{ t("common.kg") }}</span>
  </div>
</div>
```

Masthead replaces this with the inline `.mh-metrics` row produced by
`masthead_header()` (see [3.1](#31-masthead-canonical)) — don't render both on
the same page.

### Forms

`.v-label` + `.v-input` / `.v-select` / `.v-textarea` share one look: `--bg-inset`
well, `--line` border, focus ring = `--accent-line` border + `0 0 0 3px
var(--accent-soft)`. `.v-select` gets a custom SVG chevron (native arrows can't
be restyled consistently across browsers).

For anywhere a native `<select>`'s unstylable OS popup would clash with the
dark theme, use the `.v-dropdown` trio instead: `.v-dropdown-trigger` (mirrors
`.v-select` exactly) + `.v-dropdown-panel` (a floating card, add `.drop-up` when
JS detects it would overflow the viewport below) + `.v-dropdown-option`
(`.is-selected` gets the accent tint).

Date inputs use `.v-date-wrap` / `.v-date-display` to work around iOS Safari
rendering native date text centered and unreadably — JS overlays a left-aligned
span and hides the native text below 768px.

### Segmented control

`.v-seg` (track) / `.v-seg-btn.is-active` (surface-2 pill, **not** amber) — used
for the classic/masthead toggle itself, chart range pickers, and similar
mutually-exclusive choices. Also doubles as real navigation: `<a class="v-seg-btn">`
for sub-tabs that are separate routes (e.g. Garmin's Overview/Sleep/Activities).
The `a.v-seg-btn { display: block; text-decoration: none; }` pair in `vitals.css`
is what makes the class selector — written for `<button>` — behave the same on
an anchor.

### Chips, tags, pills, dots

| Class | Modifiers | Note |
|---|---|---|
| `.v-chip` | `.good`, `.bad`, `.v-chip-sm` | Neutral by default (surface-3) — deliberately **no** `.accent` modifier. `.v-chip-sm` is a compact-size modifier (10px/tight padding), combined with the base class — e.g. `class="v-chip v-chip-sm good"` — for a status badge sitting inline with a label |
| `.v-tag` | `.cool`, `.violet`, `.good`, `.bad`, `.muted` | `.cool`/`.violet` pair for day/evening-night style temporal tags |
| `.v-pill` / `.v-pill-on`, `.v-site-btn` / `.v-site-on` | — | Filter pills / body-map site picker; "selected" = neutral `--surface-2` elevation, not amber |
| `.v-dot` | `.amber`, `.cool`, `.violet`, `.good` | 7px inline status dot |

### Switch

```html
<label class="v-switch">
  <input type="checkbox" role="switch" checked hx-post="/settings/modules" …>
  <span class="v-switch-track"><span class="v-switch-thumb"></span></span>
</label>
```

Checked state turns the track `--accent-soft` and the thumb `--accent` — this is
one of the few places a *filled* amber surface appears outside the primary
button, because it's directly reporting a binary state, not decorating one.

### Table

`.v-table` — sticky `--surface` header, `--line` row dividers, `--surface-2` row
hover. `.v-num` forces tabular-nums on numeric cells. `.v-col-date`/`.v-col-actions`
pin fixed-width columns; `.v-table-wrap` scrolls horizontally on mobile;
`.hide-xs` drops low-priority columns below 480px.

`.v-night-row` — not a `.v-table` row. A CSS-grid link-row (`<a class="v-night-row">`)
that reads like a table row but is a single anchor, for lists where every row
navigates somewhere (Garmin's sleep history). See
[5.5](#55-link-row-instead-of-a-clickable-tr).

### Modal

`.v-backdrop` (blurred scrim) + `.v-modal` (surface panel). Below 640px the
modal becomes a bottom sheet: rounded top corners only, `margin-top: auto`,
capped at 92vh with internal scroll.

### Alert ladder — `info` / `warn` / `block`

```html
<div class="v-alert info">✅ {{ t("settings.saved.ui_version") }}</div>
<div class="v-alert warn">…</div>
<div class="v-alert block">…</div>
```

This is the visual half of the conflict-engine rule in `CLAUDE.md`: `info` is a
passive badge, `warn` is a status callout that never blocks, `block` is a
pre-save validation failure. See [5.1](#51-the-alertoverride-ladder) for the
full flow.

### Toast

`.v-toast-container` (fixed bottom-right, safe-area aware) / `.v-toast.is-visible`
(fade + translate in). Repositions above the bottom nav on mobile so it never
overlaps tap targets.

### Empty state & file drop

`.v-empty-state` — centered, low-opacity icon + one line of muted copy, used
wherever a list/table has no rows yet.

`.v-file-drop` (+ `__text`, `__hint`) — dashed `--bg-inset` well that turns
`--accent-soft`/`--accent-line` on hover. This exact pattern recurs everywhere
the app ingests a file: labs uploads, genetics VCF import, Garmin export,
weight body-scan photos, settings data import. Reuse it rather than styling a
one-off dropzone.

### Loading / progress

`.v-progress-bar` — a thin amber gradient sweep at the very top of the viewport
during htmx navigation (NProgress-style). `.v-loading-overlay` — full-screen
blurred scrim + spinner for a blocking operation.

## 5. Patterns

### 5.1 The alert/override ladder

Straight from the conflict-engine rule in `CLAUDE.md`, with its UI half:

1. `info` / `warn` render inline as `.v-alert` — never interrupt a save.
2. `block` + no override → the service raises `ConflictBlocked` → the router
   responds `409` with the violation payload.
3. The frontend shows [`partials/conflict_modal.html`](../web/templates/partials/conflict_modal.html):
   a `.v-modal` listing each violation (left-bordered in `--bad`, domain-pair +
   evidence line in `--faint`), ending in `.v-btn-danger` "Override" next to
   `.v-btn-ghost` "Cancel."
4. Confirming re-submits with `override: true`; the row's `override_at` is
   stamped `now`.

Reuse this exact shape for any new blocking validation — don't invent a second
confirm-dialog pattern.

### 5.2 Upload-first ingestion

Every place the app accepts an external document (lab PDF, genetics VCF,
Garmin export, InBody/MedAss photo, settings JSON import) uses the same
`.v-file-drop` well with the same two-line copy shape (bold action + muted
hint that updates to the picked filename). New import flows should match this
rather than a bespoke `<input type="file">`.

### 5.3 Markdown content (AI digests)

LLM-generated reports render through `.v-text-body`, which layers typographic
rules for `h2`–`h4`, `blockquote` (amber left-rule), inline `code` (still
tabular Inter, never mono), and tables — on top of the plain body-text class.
Wrap long-form generated content in `.v-digest` to cap line length at 52rem for
readability, independent of the card's own width.

### 5.4 One navigation registry, three consumers

Masthead's rail, its in-content tabs, and its "section N" numbering all read
from the single `MH_RUBRICS`/`MH_SECTIONS` map in `partials/masthead.html`
(see [3.1](#31-masthead-canonical)). When adding a module, register it there
once — resist the urge to add a section to just the rail or just the tabs.

### 5.5 Link-row instead of a clickable `<tr>`

`<tr>` cannot be wrapped in `<a>` — it's invalid HTML — and distributing a
click handler across every `<td>` instead has the same UX problems anyway:
dead space between cells that doesn't respond to a click, no native "open in
new tab," inconsistent hover. Where every row in a list navigates somewhere
(Garmin's sleep history, `garmin/sleep_list.html`), skip `<table>` entirely
and render each row as one `<a>` styled with CSS grid (`.v-night-row`) instead
of table markup: the whole row is the target, `:hover` is honest, and
keyboard/middle-click/"open in new tab" work for free. Reach for this pattern
any time you're tempted to make a table row clickable.

## 6. Accessibility

- **Focus rings are consistent everywhere:** `border-color: var(--accent-line)`
  + `box-shadow: 0 0 0 3px var(--accent-soft)` on inputs, dropdown triggers, and
  switches. Reuse this pair for any new focusable custom control.
- **Never put light text on the accent.** Amber (`--accent`) is a light,
  saturated color — text/icons on top of it use `--accent-ink` (`#2A1B03`), not
  white or `--fg`.
- **`prefers-reduced-motion: reduce`** is honored globally; don't ship an
  animation that bypasses standard `transition`/`animation` timing to dodge it.
- **Touch targets ≥44px** on every interactive element below 640/768px
  (buttons, segmented control, pills, icon buttons, inputs).
- **`[x-cloak]`** hides Alpine-bound markup until it's initialized — apply it
  to anything that would otherwise flash unstyled/uninitialized on load.
- **i18n is not optional:** all copy goes through `t("key")` (see
  `vitals/i18n.py`); Russian and English stay in parity. Don't hardcode a
  user-facing string in a template.

## 7. Governance — extending the system

- **Tokens live in exactly one place:** the `:root` block in `vitals.css`.
  A template should never contain a raw hex value — reference `var(--token)`
  (inline `style="color: var(--fg)"` is fine; `style="color: #F3F0F6"` is not)
  or, better, an existing `.v-*` class.
- **New semantic color?** Follow the existing pattern: a base tone plus a
  `-soft` background tint (and a `-line` border tint if it needs one), the same
  shape as `--good`/`--bad`/`--warn`/`--cool`/`--violet`. Don't add a one-off
  color outside that family.
- **Don't add a new raw Tailwind color utility.** The `slate`/`teal` remap in
  `tailwind.config.js` exists only to keep legacy markup on-theme; new markup
  should use `.v-*` classes or tokens instead of e.g. `bg-teal-600`.
- **Rebuild `web/static/tailwind.css` after touching templates or
  `tailwind.config.js`** — it's a committed artifact, not generated at runtime
  (see root `CLAUDE.md`). Run `npm run build:css` from `web/` (script defined
  in `web/package.json`), then diff the class list against the previous build
  and click through a few unrelated pages — a rescan drops classes whose
  markup disappeared, not just adds new ones.
- **Extending Masthead navigation** means editing the one registry described in
  [5.4](#54-one-navigation-registry-three-consumers) — never hand-roll a
  parallel tab list or rail-icon set for a single page.
- **Before adding a new component class**, check the inventory in
  [Section 4](#4-components) first — most needs (a status dot, a filter pill, a
  neutral tag) already have a class; a near-duplicate with a different name is
  a bug waiting to cause visual drift.
