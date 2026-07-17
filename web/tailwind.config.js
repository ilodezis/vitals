/** @type {import('tailwindcss').Config} */
//
// Vitals palette. The templates lean heavily on `slate-*` (surfaces/text) and
// `teal-*` (the accent). Rather than rewrite thousands of utility classes we
// REMAP those two scales here to the warm "health companion" theme:
//   slate → warm plum-charcoal   |   teal → honey-amber accent
// Extra shades (250/350/450/650/750/850/955) that the markup references are
// defined too, so nothing silently falls back to an undefined colour.
//
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/**/*.js",
    "!./static/vendor/**"
  ],
  theme: {
    extend: {
      colors: {
        // Warm neutral surfaces + text (replaces cool blue "slate")
        slate: {
          50:  "#F7F5FA",
          100: "#EFECF4",
          200: "#E1DCE9",
          250: "#D6D0E0",
          300: "#C7C0D3",
          350: "#B6AEC5",
          400: "#A39AB0",
          450: "#8F8799",
          500: "#7C7488",
          600: "#5C5667",
          650: "#4F4958",
          700: "#3E3947",
          750: "#393440",
          800: "#2C2933",
          850: "#262230",
          900: "#232027",
          950: "#1B1920",
        },
        // Honey-amber accent (replaces "teal")
        teal: {
          300: "#FFCE85",
          400: "#FBB54C",
          500: "#F5A623",
          600: "#EA9A12",
          700: "#C77F08",
          800: "#9A6206",
          900: "#4A370F",
          950: "#34270D",
          955: "#2A2009",
        },
        // Soft dark tints referenced as `<hue>-955`
        amber:   { 955: "#2A2009" },
        rose:    { 955: "#33141A" },
        sky:     { 955: "#0B2733" },
        emerald: { 955: "#0E2A20" },
      },
      fontFamily: {
        // No monospace in the product — alias `mono` to Inter so any stray
        // `font-mono` renders as tabular Inter (see vitals.css).
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
        mono: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
      }
    }
  },
  plugins: []
}
