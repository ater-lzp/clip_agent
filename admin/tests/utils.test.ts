import { describe, expect, it } from 'vitest'
import { formatDate, yuanToCents } from '../src/utils'

describe('admin formatting', () => {
  it('always renders UTC timestamps in Asia/Shanghai', () => {
    expect(formatDate('2026-08-04T00:00:00Z')).toContain('2026')
    expect(formatDate('2026-08-04T00:00:00Z')).toContain('08:00')
  })

  it('converts yuan to integer cents without floating point drift', () => {
    expect(yuanToCents(29.9)).toBe(2990)
    expect(yuanToCents(0.01)).toBe(1)
  })
})
