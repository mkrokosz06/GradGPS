/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,jsx,ts,tsx}", "./components/**/*.{js,jsx,ts,tsx}"],
  presets: [require("nativewind/preset")],
  theme: {
    extend: {
      colors: {
        navy: "#1a3a6b",
        "navy-light": "#2a5298",
        gold: "#E8C84B",
        done: "#22c55e",
        progress: "#f59e0b",
        missing: "#ef4444",
      },
    },
  },
  plugins: [],
};
