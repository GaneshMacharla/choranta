/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#040d12',
        surface: '#091b22',
        'surface-hover': '#0f2934',
        'surface-card': '#0a1e27',
        'surface-input': '#06141a',
        border: '#143c49',
        'border-subtle': '#0e2933',
        accent: '#00df8f',
        'accent-hover': '#00f59b',
        'accent-dark': '#00b875',
        'accent-foreground': '#022016',
        muted: '#62818e',
        mint: {
          50: '#e6fcf5',
          100: '#bbf7e3',
          200: '#82eecb',
          300: '#45e0af',
          400: '#16d196',
          500: '#00df8f',
          600: '#00c07a',
          700: '#009862',
          800: '#04754d',
          900: '#055f3f',
          950: '#022016',
        },
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      boxShadow: {
        'mint-glow': '0 0 20px -2px rgba(0, 223, 143, 0.35)',
        'mint-glow-sm': '0 0 10px -2px rgba(0, 223, 143, 0.25)',
      }
    },
  },
  plugins: [],
}
