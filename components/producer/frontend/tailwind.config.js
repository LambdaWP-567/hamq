/** @type {import('tailwindcss').Config} */
export default {
  // Scan all TypeScript/TSX source files for class names
  content: [
    './index.html',
    './src/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      // Custom colour aliases that match the HAMq brand
      colors: {
        brand: {
          50:  '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
        },
      },
    },
  },
  plugins: [
    // Provides nice default styles for form elements (input, select, etc.)
    require('@tailwindcss/forms'),
  ],
}
