import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ThemeToggle from '../src/components/ThemeToggle.vue'

describe('ThemeToggle', () => {
  it('switches the root theme and persists the preference', async () => {
    const wrapper = mount(ThemeToggle)
    const before = document.documentElement.classList.contains('theme-light')
    await wrapper.get('button').trigger('click')
    expect(document.documentElement.classList.contains('theme-light')).toBe(!before)
    expect(window.localStorage.getItem('clip-theme')).toBe(before ? 'dark' : 'light')
  })
})
