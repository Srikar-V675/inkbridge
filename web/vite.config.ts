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

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), devLog],
})
