import type { ApiErrorPayload } from '../types/domain'

const apiBase = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId: string
  readonly fields: Array<{ field: string; message: string }>
  readonly retryable: boolean

  constructor(status: number, payload: ApiErrorPayload['error']) {
    super(payload.message)
    this.name = 'ApiError'
    this.status = status
    this.code = payload.code
    this.requestId = payload.request_id
    this.fields = payload.fields ?? []
    this.retryable = payload.retryable
  }
}

function cookie(name: string): string | null {
  const prefix = `${encodeURIComponent(name)}=`
  const entry = document.cookie.split('; ').find((item) => item.startsWith(prefix))
  return entry ? decodeURIComponent(entry.slice(prefix.length)) : null
}

function isErrorPayload(value: unknown): value is ApiErrorPayload {
  if (!value || typeof value !== 'object' || !('error' in value)) return false
  const error = (value as { error: unknown }).error
  return Boolean(
    error &&
      typeof error === 'object' &&
      'code' in error &&
      typeof error.code === 'string' &&
      'message' in error &&
      typeof error.message === 'string' &&
      'request_id' in error &&
      typeof error.request_id === 'string',
  )
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  timeoutMs?: number
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, timeoutMs, ...fetchOptions } = options
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs ?? 20_000)
  const method = (options.method ?? 'GET').toUpperCase()
  const headers = new Headers(options.headers)
  headers.set('Accept', 'application/json')
  if (body !== undefined) headers.set('Content-Type', 'application/json')
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrf = cookie('clip_csrf')
    if (csrf) headers.set('X-CSRF-Token', csrf)
  }
  try {
    const response = await fetch(`${apiBase}${path}`, {
      ...fetchOptions,
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'include',
      signal: controller.signal,
    })
    if (!response.ok) {
      const payload: unknown = await response.json().catch(() => null)
      if (response.status === 401) window.dispatchEvent(new Event('clip:unauthorized'))
      if (isErrorPayload(payload)) throw new ApiError(response.status, payload.error)
      throw new ApiError(response.status, {
        code: 'INVALID_RESPONSE',
        message: '服务返回了无法识别的错误',
        request_id: response.headers.get('X-Request-ID') ?? 'unknown',
        retryable: response.status >= 500,
      })
    }
    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError(0, {
        code: 'REQUEST_TIMEOUT',
        message: '请求超时，请检查连接后重试',
        request_id: 'client',
        retryable: true,
      })
    }
    throw error
  } finally {
    window.clearTimeout(timeout)
  }
}

export function absoluteApiUrl(path: string): string {
  return `${apiBase}${path}`
}
