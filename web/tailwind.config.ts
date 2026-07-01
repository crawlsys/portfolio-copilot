import type { Config } from "tailwindcss";
import tailwindcssAnimate from "tailwindcss-animate";

// Tremor builds chart color classes dynamically (e.g. `fill-cyan-500`) inside
// its minified bundle, so Tailwind's content scanner never sees them as
// literals and doesn't emit the CSS — charts render with no fill (black).
// Safelist the chart color/shade combos we use so the classes always exist.
const TREMOR_CHART_COLORS = [
  "cyan", "emerald", "amber", "rose", "indigo",
  "violet", "sky", "teal", "blue", "green", "orange", "pink",
];
const TREMOR_CHART_SHADES = ["400", "500", "600"];

const config: Config = {
  darkMode: ["class"],
  content: [
    "./src/**/*.{ts,tsx}",
    "./node_modules/@tremor/**/*.{js,ts,jsx,tsx}",
  ],
  safelist: [
    // fill-* (donut/bar segment fills) + dark variants
    ...TREMOR_CHART_COLORS.flatMap((c) =>
      TREMOR_CHART_SHADES.flatMap((s) => [
        `fill-${c}-${s}`,
        `dark:fill-${c}-${s}`,
        `stroke-${c}-${s}`,
        `dark:stroke-${c}-${s}`,
      ]),
    ),
    // Tremor component text/border tokens used in tooltips
    ...TREMOR_CHART_COLORS.flatMap((c) =>
      TREMOR_CHART_SHADES.flatMap((s) => [
        `text-${c}-${s}`,
        `dark:text-${c}-${s}`,
        `bg-${c}-${s}`,
        `dark:bg-${c}-${s}`,
      ]),
    ),
  ],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
    },
  },
  plugins: [tailwindcssAnimate],
};

export default config;
