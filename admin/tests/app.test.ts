import { describe, expect, it } from 'vitest'
import router from '../src/router'

describe('admin app', () => {
  it('provides separate operations pages', () => {
    expect(router.resolve('/').name).toBe('overview')
    expect(router.resolve('/users').name).toBe('users')
    expect(router.resolve('/tasks').name).toBe('tasks')
    expect(router.resolve('/cdks').name).toBe('cdks')
    expect(router.resolve('/audit-logs').name).toBe('audit-logs')
    expect(router.resolve('/login').name).toBe('login')
  })
})
