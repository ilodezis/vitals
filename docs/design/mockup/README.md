# Vitals redesign mockup

The reference for the redesign: the approved screens, shell, controls, icons and
motion that the React app in `frontend/` is built to match. When the app and the
mockup disagree on how something looks or moves, the mockup is right.

- `vitals-redesign.html` — the whole mockup in one file. Open it with a double
  click; no server needed.
- `src/` — its sources: `styles.css` (tokens under `:root`, then every component),
  `app.js` (screens, navigation, motion), `data.js` (deterministic demo data),
  `viewer.js` and `shell.html` (the device frames around the app — not product).
- `icons.js` — the icon family on its own (24 grid, 1.6 stroke, quiet fill on the
  form); the same dictionary is inlined in `src/app.js`.

Edit the sources, then rebuild the single file:

```
python build.py
```

URL parameters:

- `?mode=phone|desk|both` — which frame to show (default `both`).
- `&screen=<id>` — the screen to open on, e.g. `today`, `weight`, `recovery`,
  `glp1`, `labs`, `more`.

Example: `vitals-redesign.html?mode=phone&screen=weight`.

The demo data is synthetic. Fonts load from Google Fonts here; the app self-hosts
them.
