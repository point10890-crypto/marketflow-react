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
        // Anthropic / Claude design language
        // Reference: claude.ai, console.anthropic.com, anthropic.com
        anthropic: {
          // Light (editorial cream)
          cream: '#F0EEE6',
          cream2: '#FAF9F5',
          ink: '#1A1915',
          ink2: '#141413',
          gray: '#6B6962',
          line: '#DDD9CE',
          // Warm dark (claude.ai chat)
          dark: '#262624',
          dark2: '#2C2A26',
          darkLine: '#3A3833',
          darkText: '#E8E5DD',
          darkMuted: '#8A8780',
          // Single accent
          orange: '#CC785C',
          orangeHover: '#B8593F',
          orangeDim: '#CC785C26',  // 15% opacity for tints
        },
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"SF Pro Text"', '"Segoe UI"', 'Inter', 'sans-serif'],
        serif: ['"Source Serif Pro"', '"Charter"', '"Iowan Old Style"', 'Georgia', 'serif'],
        mono: ['"JetBrains Mono"', '"SF Mono"', 'Menlo', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
};
