import { defineConfig } from 'vite';

// The "/api" proxy lets the dev server talk to the Python backend without CORS problems.
export default defineConfig({
  esbuild: { jsx: 'automatic' },
  server: { port: 5173, host: true, proxy: { '/api': 'http://127.0.0.1:8000' } },
  preview: { proxy: { '/api': 'http://127.0.0.1:8000' } },
});
