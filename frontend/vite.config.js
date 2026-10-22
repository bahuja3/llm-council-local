import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Pin loopback. Vite's omitted-host default is localhost; this keeps the
    // dev server off LAN addresses even if that default changes.
    host: '127.0.0.1',
  },
})
