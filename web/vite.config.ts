import react from '@vitejs/plugin-react'
import { appendFileSync } from 'node:fs'
import { defineConfig } from 'vite'

// Dev-only: POST /__log appends the body to dev.log so the agent can read device logs.
const devLog = {
  name: 'dev-log',
  configureServer(server: any) {
    server.middlewares.use('/__log', (req: any, res: any) => {
      let body = ''
      req.on('data', (c: any) => (body += c))
      req.on('end', () => {
        appendFileSync('dev.log', `${new Date().toISOString()} ${body}\n`)
        res.end('ok')
      })
    })
  },
}

// The API sends no CORS headers, so the dev server proxies it: the tablet only needs this one URL.
const api = process.env.INKBRIDGE_API_URL ?? 'http://127.0.0.1:8000'
const proxied = ['/documents', '/ops', '/regions', '/search', '/health']

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), devLog],
  server: {
    proxy: {
      ...Object.fromEntries(proxied.map((p) => [p, api])),
      '/ws': { target: api, ws: true },
    },
  },
})
