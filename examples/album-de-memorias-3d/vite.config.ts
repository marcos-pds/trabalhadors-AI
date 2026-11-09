import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  // GitHub Pages uses the repository name as a subpath.
  base: process.env.GITHUB_PAGES === 'true' ? '/trabalhadors-AI/' : '/',
  plugins: [react(), tailwindcss()],
})
