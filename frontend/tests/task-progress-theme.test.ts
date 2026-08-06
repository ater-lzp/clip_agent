import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const styles = readFileSync(resolve(process.cwd(), 'src/styles.css'), 'utf8')

describe('TaskProgress light theme', () => {
  it('uses light theme tokens instead of a fixed dark background', () => {
    expect(styles).toContain('--progress-bg: #eaf6fd;')
    expect(styles).toContain('--progress-track-bg: #c5e2f2;')
    expect(styles).toContain('background: var(--progress-bg)')
    expect(styles).toContain('background: var(--progress-track-bg)')
  })
})
