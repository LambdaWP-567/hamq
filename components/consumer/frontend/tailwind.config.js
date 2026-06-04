/** @type {import('tailwindcss').Config} */
export default {
  // Scan all TypeScript/TSX source files for class names.
  content: [
    './index.html',
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // HAMq Consumer brand colours (blue-teal palette — distinct from
        // the producer's green palette for easy visual differentiation).
        brand: {
          50:  '#f0fdfa',
          100: '#ccfbf1',
          200: '#99f6e4',
          300: '#5eead4',
          400: '#2dd4bf',
          500: '#14b8a6',
          600: '#0d9488',
          700: '#0f766e',
          800: '#115e59',
          900: '#134e4a',
        },
      },
    },
  },
  plugins: [],
}
