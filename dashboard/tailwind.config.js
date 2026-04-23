/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // 트레이딩 특화 시맨틱 컬러
        'buy':  '#16a34a',
        'sell': '#dc2626',
        'stop': '#f59e0b',
        'hold': '#6b7280',
      },
    },
  },
  plugins: [],
};
