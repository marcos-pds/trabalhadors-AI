import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ mode }) => ({
  // Use "vite build --mode pages" for the repository GitHub Pages subpath.
  base: mode === 'pages' ? '/trabalhadors-AI/' : '/',
  plugins: [react(), tailwindcss()],
}))
