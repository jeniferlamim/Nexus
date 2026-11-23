/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 950: "#050a14", 900: "#070d18", 850: "#0a111f", 800: "#0d1525", 750: "#0f1726", 700: "#131d30", 600: "#1a2538", 500: "#243149", 400: "#33425e" },
        fg: { DEFAULT: "#e6ebf3", 2: "#a7b2c5", 3: "#76839a", 4: "#525e73" },
        accent: { DEFAULT: "#2ed39a", dim: "#1f9b70", ink: "#062a1e" },
        navy: { DEFAULT: "#1b3a6b", 2: "#264f8f" },
        series: { rec: "#199e70", exp: "#d95926", div: "#3987e5" },
        status: { good: "#0ca30c", warning: "#fab219", serious: "#ec835a", critical: "#d03b3b" },
      },
      fontFamily: {
        sans: ['"Inter Variable"', "Inter", "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      fontSize: { "2xs": ["10.5px", "14px"] },
      boxShadow: { panel: "0 0 0 1px rgba(255,255,255,0.03), 0 8px 24px -12px rgba(0,0,0,0.6)" },
    },
  },
  plugins: [],
};
