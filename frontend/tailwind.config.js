/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        brand: {
          50:  '#f0f4ff',
          100: '#dce5ff',
          200: '#c0ceff',
          300: '#93a8fc',
          400: '#6478f8',
          500: '#4451f1',
          600: '#3330e6',
          700: '#2b26cb',
          800: '#2622a4',
          900: '#252381',
          950: '#17154d',
        },
        surface: {
          900: '#0a0b0f',
          800: '#0f1117',
          700: '#14161f',
          600: '#1a1d28',
          500: '#1f2233',
          400: '#252840',
          300: '#2e324e',
        },
        status: {
          triggered:  '#f59e0b',
          diagnosing: '#8b5cf6',
          drafting:   '#3b82f6',
          checking:   '#f97316',
          remediated: '#10b981',
          escalated:  '#ef4444',
          error:      '#dc2626',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Cascadia Code', 'ui-monospace', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'spin-slow':  'spin 3s linear infinite',
        'fade-in':    'fadeIn 0.4s ease-out',
        'slide-up':   'slideUp 0.4s ease-out',
        'glow':       'glow 2s ease-in-out infinite alternate',
      },
      keyframes: {
        fadeIn: {
          '0%':   { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%':   { opacity: '0', transform: 'translateY(16px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        glow: {
          '0%':   { boxShadow: '0 0 5px rgba(99,102,241,0.3)' },
          '100%': { boxShadow: '0 0 20px rgba(99,102,241,0.7)' },
        },
      },
      backgroundImage: {
        'grid-pattern': `
          linear-gradient(rgba(99,102,241,0.04) 1px, transparent 1px),
          linear-gradient(90deg, rgba(99,102,241,0.04) 1px, transparent 1px)
        `,
      },
      backgroundSize: {
        'grid': '32px 32px',
      },
    },
  },
  plugins: [],
}
