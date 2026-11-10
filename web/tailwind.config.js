/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        caos: {
          negro: "#060607",
          tinta: "#101013",
          tintaElevada: "#17171C",
          borde: "#26262A",
          bordeLight: "#38383E",
          tenue: "#5C5C5A",
          gris: "#93938F",
          hueso: "#EDEAE5",
          champan: "#EBD3BB",
          ambar: "#C9975C",
          ambarMuted: "rgba(201, 151, 92, 0.15)",
          redMuted: "rgba(220, 38, 38, 0.15)",
          redText: "#EF4444",
          greenMuted: "rgba(34, 197, 94, 0.15)",
          greenText: "#22C55E",
          blueMuted: "rgba(59, 130, 246, 0.15)",
          blueText: "#60A5FA",
        }
      },
      fontFamily: {
        brand: ["UnifrakturMaguntia", "serif"],
        serif: ["EB Garamond", "serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      borderRadius: {
        none: "0px",
      }
    },
  },
  plugins: [],
}
