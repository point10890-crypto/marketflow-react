/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        accent: '#2997ff',
        success: '#30d158',
        danger: '#ff453a',
        warning: '#ff9f0a',
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"SF Pro Text"', '"Segoe UI"', 'Inter', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
