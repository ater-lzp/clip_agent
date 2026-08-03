import { describe, expect, it } from 'vitest'
import { formatDuration } from '../src/utils/format'

describe('formatDuration', () => {
  it('uses one consistent clock format', () => {
    expect(formatDuration(0)).toBe('00:00')
    expect(formatDuration(61)).toBe('01:01')
    expect(formatDuration(3661)).toBe('01:01:01')
  })

  it('clamps negative values', () => {
    expect(formatDuration(-8)).toBe('00:00')
  })
})

