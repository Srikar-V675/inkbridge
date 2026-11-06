import { useState } from 'react'
import tokensCss from '../styles/tokens.css?raw'
import { Badge } from './Badge.tsx'
import { Button } from './Button.tsx'
import { Card } from './Card.tsx'
import { Chip } from './Chip.tsx'
import { IconButton } from './IconButton.tsx'
import { Panel } from './Panel.tsx'
import { StatusDot } from './StatusDot.tsx'
import { parseTokenCss } from './tokenTable.ts'
import { Toast } from './Toast.tsx'
import './Kit.css'

// Dev-only page (INK-160, main.tsx loads it behind import.meta.env.DEV and ?kit=1).
// Swatches come from tokens.css at runtime, so no colour name is spelled in this file.
const tokens = parseTokenCss(tokensCss)
const colors = tokens.filter((t) => t.name.startsWith('--color-') && !t.name.startsWith('--color-pen-'))
const pens = tokens.filter((t) => t.name.startsWith('--color-pen-'))
const scale = tokens.filter((t) => /^--(radius|space)-/.test(t.name) || /^--type-[a-z-]+-size$/.test(t.name))
// The agent colour for the proportions bar: whatever the draft badge uses, taken as data.
const agent = tokens.find((t) => t.name.startsWith('--component-draft-badge-') && t.name.endsWith('-background-color'))?.value

const label = (name: string) => name.replace(/^--color-/, '').replace(/-/g, ' ')

function Swatch({ name, value }: { name: string; value: string }) {
  return (
    <div className="ink-kit__swatch">
      <div className="ink-kit__swatch-box" style={{ background: `var(${name})` }} />
      <b>{label(name)}</b>
      <span>{value}</span>
    </div>
  )
}

export function Kit() {
  const [toastKey, setToastKey] = useState(0)
  const [toastOpen, setToastOpen] = useState(false)
  const showToast = () => {
    setToastKey((k) => k + 1)
    setToastOpen(true)
  }
  const hideToast = () => setToastOpen(false)

  return (
    <div className="ink-kit">
      <section className="ink-kit__col">
        <div>
          <h1 className="ink-kit__wordmark">Paper, charcoal and one highlighter</h1>
          <p className="ink-kit__reading">Warm paper and charcoal carry the whole app. The highlighter is the agent, and nothing else.</p>
        </div>

        <div className="ink-kit__bar" role="img" aria-label="Proportions: paper 60, charcoal 30, agent 10">
          <div style={{ flex: 60, background: 'var(--color-panel)' }}>Paper 60</div>
          <div style={{ flex: 30, background: 'var(--color-charcoal)', color: 'var(--color-paper)' }}>Charcoal 30</div>
          <div style={{ flex: 10, background: agent, justifyContent: 'center', paddingLeft: 0 }}>10</div>
        </div>

        <div className="ink-kit__swatches">
          {colors.map((t) => (
            <Swatch key={t.name} name={t.name} value={t.value} />
          ))}
        </div>

        <div>
          <h2 className="ink-kit__title">Pen colours</h2>
          <div className="ink-kit__pens">
            {pens.map((t) => (
              <span key={t.name}>
                <span className="ink-kit__pen" style={{ background: `var(${t.name})` }} />
                {label(t.name.replace('--color-pen-', '--color-'))}
              </span>
            ))}
            <span className="ink-kit__note">Your ink, never the agent colour.</span>
          </div>
        </div>

        <div>
          <h2 className="ink-kit__title">Radii, spacing and type sizes</h2>
          <table className="ink-kit__table">
            <tbody>
              {scale.map((t) => (
                <tr key={t.name}>
                  <td>{t.name}</td>
                  <td>{t.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="ink-kit__col">
        <div>
          <h2 className="ink-kit__title">Type: Instrument Sans</h2>
          <p className="ink-kit__t ink-kit__t--wordmark">24 Wordmark, home titles</p>
          <p className="ink-kit__t ink-kit__t--title">20 Section and thread titles</p>
          <p className="ink-kit__t ink-kit__t--reading">17 Reading text in answers and drafts</p>
          <p className="ink-kit__t ink-kit__t--control">15 Buttons and chips</p>
          <p className="ink-kit__t ink-kit__t--note">14 Notes and status</p>
        </div>

        <div>
          <h2 className="ink-kit__title">Controls, 44 px or taller</h2>
          <div className="ink-kit__row">
            <Button variant="primary">Primary</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="quiet">Quiet</Button>
            <IconButton label="Undo">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M9 14L4 9l5-5" />
                <path d="M4 9h10a6 6 0 0 1 0 12h-3" />
              </svg>
            </IconButton>
            <Chip>Offer</Chip>
            <Badge />
          </div>
        </div>

        <div className="ink-kit__row ink-kit__row--top">
          <Card>
            <p className="ink-kit__t ink-kit__t--reading">A card holds a draft or a canvas.</p>
          </Card>
          <Panel title="Side panel">
            <p className="ink-kit__t ink-kit__t--note">440 px wide, no shadow.</p>
          </Panel>
        </div>

        <div>
          <h2 className="ink-kit__title">Toast</h2>
          <div className="ink-kit__row">
            <Button variant="secondary" onClick={showToast}>
              Show toast
            </Button>
            {toastOpen && <Toast key={toastKey} message="Draft removed" actionLabel="Undo" onAction={hideToast} onDismiss={hideToast} />}
          </div>
        </div>

        <div>
          <h2 className="ink-kit__title">Saving, shown only when it matters</h2>
          <div className="ink-kit__saving">
            <span>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M5 12l5 5 9-10" />
              </svg>
              <span className="ink-kit__note">Saved. Quiet by default, nothing to watch.</span>
            </span>
            <span>
              <StatusDot tone="sending" />
              Kept on this tablet, sending when the network is back
            </span>
            <span className="ink-kit__risk">
              <StatusDot tone="risk" />
              Ink only in memory: do not close this tab
            </span>
          </div>
        </div>
      </section>
    </div>
  )
}
