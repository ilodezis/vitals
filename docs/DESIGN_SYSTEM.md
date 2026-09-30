# Vitals — Design System

The interface is a React app in [`frontend/`](../frontend): TanStack Router for the screens, TanStack
Query for data, Vite for the build, installed as a PWA. This document describes the system as the
code implements it; if you change a token, a control or a rule below, change this file in the same
PR.

## At a glance

- **A warm health companion, not a clinical terminal.** Dim plum-charcoal surfaces, never pure black,
  never white.
- **One accent, spent on purpose.** Amber (`--accent`) means *now / you are here / the one action*: the
  active navigation item, the primary button, the live reading. Data values, chips and decoration stay
  neutral, so the accent keeps its meaning.
- **No monospace, anywhere.** Figures are set in the text face with tabular numerals, so columns still
  line up.
- **One type ladder, no others.** Text sits on a rung of `--t-*`; only display figures go above it.
- **A ladder of alerts, not a wall of red.** `note`, `info`, `warn`, `block`. Calm by default; loud only
  when a save must actually be stopped.
- **A navigator, not an overseer.** It shows the data and lets the owner decide.

## 1. Foundations

All of it lives in [`frontend/src/styles/tokens.css`](../frontend/src/styles/tokens.css). Nothing in
the app hard-codes a colour, size, radius or duration that a token already names.

| Group | Tokens |
|---|---|
| Surfaces | `--bg`, `--bg-deep`, `--surface`, `--surface-2`, `--surface-3`, `--line`, `--line-2` |
| Text | `--fg`, `--fg-2`, `--muted`, `--faint` |
| Accent | `--accent`, `--accent-2`, `--accent-ink`, `--accent-soft`, `--accent-line` |
| Meaning | `--good`, `--bad` (`--bad-strong`), `--warn`, `--cool`, `--violet`, `--deep`, each with `-soft` (13 %) and `-line` (30 %) |
| Type | `--f-display` (Geologica Variable), `--f-text` (Golos Text Variable) |
| Ladder | `--t-eyebrow` 11 · `--t-micro` 12 · `--t-label` 13 · `--t-body` 14 · `--t-ui` 15 · `--t-heading` 18 · `--t-lead` 22 · `--t-title` 28 · `--t-display` 38 · `--t-hero` 56 |
| Space | `--s1` 4 … `--s12` 48 |
| Shape | `--r-xs` 8 · `--r-sm` 10 · `--r` 14 · `--r-lg` 20 · `--r-pill` |
| Motion | `--ease-out`, `--ease-io`, `--ease-sheet`; `--d1` 120 · `--d2` 200 · `--d3` 320 · `--d4` 480 ms |

Both families carry Cyrillic. The display face falls back to the text face, never straight to a generic
family. The server-rendered pages (sign-in, OAuth, 404, the doctor's report notices) use the same two
families from `web/static/fonts`.

### Colour

- Semantic colours come in three strengths: the base for text and marks, `-soft` for a tinted fill,
  `-line` for a border. A border never mixes its own colour.
- Text on a surface uses `--fg`, `--fg-2`, `--muted`, `--faint` in that order of weight. Contrast of
  `--muted` on `--surface` is the floor for anything that has to be read.
- The accent is not a value colour. A reading that is out of range is `--bad`; one that is good is
  `--good`; nothing is amber because it is "important".

### Type

- Display figures (the weight on Today, a dose) are set in `--f-display` at `--t-hero` or
  `--t-display`; body and UI text in `--f-text`.
- Numerals are tabular wherever they change or line up. A reel of digits (the odometer) is centred in
  its column so a narrow "1" does not open a gap.
- Nothing is set below 11 px. A size that is not on the ladder needs a reason in
  `src/styles/designRules.test.ts`, which also keeps new ones out.

### Shape and motion

- Corners come from `--r-*`. The exceptions are not corners: a hairline bar's 1–4 px, a circle, a pill,
  and the bottom sheet's top edge.
- A transition names what it animates; `transition: all` is not allowed.
- One vocabulary of easings and durations, in `src/lib/motion.ts`, as Web Animations. Under
  `prefers-reduced-motion` every motion is a cut.

## 2. Layout and shell

The app is one container with two layouts, chosen by the container's width (CSS container queries,
and `useLayout()` for the few things drawn in script):

- **From 768 px** a rail (sections, status card, account) beside a stage; one screen shows at a time.
- **Below 768 px** a stage over a five-column bottom bar: Today, three rubric or section columns, More.
  The screens you came through stay mounted under the current one, so *back* is a slide, and an edge
  swipe goes back.

The navigation comes from the server: `GET /api/v1/session` returns the sections that are on, in rail
order (`MODULE_REGISTRY` in `vitals/services/modules_service.py`). A section that is switched off
leaves every surface; the Settings list comes from the full registry, so it can be switched back on.

A screen is a file in `src/routes` (lazy) and an entry in `SCREEN_PATH`
(`src/components/shell/nav.ts`); the server serves the shell on its address (`SPA_SCREENS` in
`web/spa.py`).

### Screen transitions

`Stage` owns the stack; the router owns the address. A change of address becomes a plan
(`planGo`) and the plan a motion: a push slides in over the screen below (540 ms, with the 0.28
parallax and 0.32 shade), a tab or a section change cross-fades, Today's weight figure morphs into the
Weight page's hero. A screen that has left is hidden before its motion's fill is released, so it can
never flash back over the new one.

## 3. Components

| Control | Where | Rule |
|---|---|---|
| `Section`, `SectionTabs` | `components/controls` | A screen is sections with a heading row; tabs switch sections in place |
| `PrimaryButton` | | The one amber button of a screen; shows its own progress and outcome |
| `Segmented`, `Choices` | | Pills, not radio dots; the chosen one is filled |
| `.tgl` switch, 1–5 scale group | | The app's own controls; the browser's checkbox and range input are not used (guarded by `noBrowserControls.test.ts`) |
| `Stepper` | | Weight and dose entry; holding it repeats |
| `Disclosure` | | The only collapsible arrow |
| `Alert`, `DomainAlerts`, `ConflictAlert` | | The alert ladder; a conflict offers "Fix it" and "Save anyway" |
| `ConfirmButton` | | A destructive action asks once, in place |
| `Odometer` | | Digits as reels; the figure rolls to a new value of the same shape |
| `Meters` | | Range bars and gauges |
| `LogSheet` | `components/sheet` | The entry sheet: a bottom sheet on the phone, a side drawer on the desktop |

Forms opened in place share one layout (`.fpanel`, `.form-acts`, `.form-g2`, `.fhint` in `app.css`);
a screen's own stylesheet loads only with that screen, so form layout never lives there
(`sharedFormStyles.test.ts`). A button is `.btn` *or* `.ghost`, never both.

### Icons

One family in `components/icons`: 24-unit viewBox, 1.6 stroke, round caps, a quiet fill on the form
that is fuller when active. An icon is one em unless a parent sizes it. An icon-only button has an
accessible name and keeps a 44 px touch target.

### Charts

Drawn as SVG at the real pixel width of their box (`ChartFrame`, `useElementWidth`). The geometry
(scales from d3-scale, curves from d3-shape) is pure and tested (`components/charts/geometry.ts`):
every chart clips to its plot, so a reading outside the visible range cannot draw over its neighbours.
A weight trend is monotone (it never overshoots a reading); a dose is a step.

## 4. Language

All copy is in the catalogue (`vitals/i18n.py`, RU and EN) and reaches the app as a dictionary
(`npm --prefix frontend run gen:i18n`). No string literal in Cyrillic, and no JSX text, in
`src/features` or `src/components` (`noHardcodedCopy.test.ts`). Numbers and dates are formatted by
`src/lib/format.ts` and `src/lib/dates.ts` for the current language, with one decimal mark per
language.

## 5. Accessibility

- Every interactive element is reachable by keyboard; the sheet closes on `Esc` and opens on `N`.
- Every icon-only control is named; every control has an `:active` state.
- Numeric fields ask for the right keyboard (`inputMode`).
- Colour is never the only carrier of meaning: out-of-range readings also say so in words.
- Reduced motion turns every motion into a cut.

## 6. Guards

What keeps the system from drifting is tests, run with `npm --prefix frontend run check`:

| Test | Keeps |
|---|---|
| `styles/tokens.test.ts` | the tokens equal the mockup's; the display face never falls to a generic family |
| `styles/designRules.test.ts` | the type ladder, radii from tokens, no `transition: all`, 44 px icon buttons |
| `noMonospace.test.ts`, `noTailwind.test.ts` | no monospace face, no utility-class framework |
| `noHardcodedCopy.test.ts` | no literal copy outside the catalogue |
| `noBrowserControls.test.ts`, `noAmberGhost.test.ts`, `sharedFormStyles.test.ts` | one control vocabulary |
| `iconGuards.test.ts` | one icon size, one collapsible arrow |
| `check-size.mjs` | the startup bundle stays under its budget |

## 7. Extending the system

1. Take the value from a token; if none fits, add the token to the mockup first, then to
   `tokens.css`, and update the table above.
2. Reuse a control before writing one. A new control goes in `components/controls` with its rule here.
3. A new screen: a route file, `SCREEN_PATH`, `SPA_SCREENS`, the module in the registry if it can be
   switched off, strings in the catalogue.
4. Check it in a browser at 402×874 and at 1440×900 with the console open.
