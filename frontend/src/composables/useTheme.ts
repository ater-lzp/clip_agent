import { readonly, ref } from 'vue'

export type Theme = 'light' | 'dark'

function storedTheme(): Theme {
  try {
    const value = window.localStorage.getItem('clip-theme')
    return value === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

const theme = ref<Theme>(storedTheme())

function applyTheme(value: Theme): void {
  theme.value = value
  document.documentElement.classList.toggle('theme-light', value === 'light')
  document.documentElement.classList.toggle('theme-dark', value === 'dark')
  document.documentElement.style.colorScheme = value
  try {
    window.localStorage.setItem('clip-theme', value)
  } catch {
    // Theme persistence is optional when storage is unavailable.
  }
}

applyTheme(theme.value)

export function useTheme() {
  return {
    theme: readonly(theme),
    toggle() {
      applyTheme(theme.value === 'dark' ? 'light' : 'dark')
    },
  }
}
