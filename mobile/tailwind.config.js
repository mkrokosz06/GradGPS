/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,jsx,ts,tsx}", "./components/**/*.{js,jsx,ts,tsx}", "./context/**/*.{js,jsx,ts,tsx}"],
  presets: [require("nativewind/preset")],
  theme: {
    extend: {
      colors: {
        navy:       "#1a3a6b",
        "navy-mid": "#2a5298",
        gold:       "#E8C84B",
        done:       "#16a34a",
        progress:   "#d97706",
        missing:    "#9ca3af",
      },
    },
  },
  plugins: [],
};
