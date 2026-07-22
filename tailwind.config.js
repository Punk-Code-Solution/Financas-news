/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/js/**/*.js",
  ],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "sans-serif"],
      },
      opacity: {
        45: "0.45",
      },
    },
  },
  plugins: [],
  safelist: [
    "bg-blue-600",
    "text-white",
    "dark:bg-[#4ade80]",
    "dark:text-slate-900",
    "ring-2",
    "ring-blue-500",
    "dark:ring-[#4ade80]",
    "shadow-md",
    "opacity-45",
    "scale-[0.98]",
  ],
};
