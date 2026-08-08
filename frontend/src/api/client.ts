import { accessToken } from '@/auth'

interface Envelope<T> { correlation_id: string; state: string; result: T }
export interface Dashboard { billing_lines: number; total_amount: string; query_runs: number; open_findings: number; tickets: number }
export interface QueryPlan { plan_id: string; kind: string; statement: string; ast_allowed: boolean; estimated_cost: string; budget_limit: string; status: string; expires_at: number }
export interface QueryResult { query_id: string; status: string; page: Array<Record<string, unknown>>; [key: string]: unknown }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const bearer = accessToken()
  if (bearer) headers.set('Authorization', `Bearer ${bearer}`)
  if (init.body) headers.set('Content-Type', 'application/json')
  headers.set('X-Request-Id', crypto.randomUUID())
  const response = await fetch(`/api${path}`, { ...init, headers })
  if (!response.ok) throw new Error(await response.text() || `HTTP ${response.status}`)
  const body = await response.json() as Envelope<T>
  return body.result ?? body as T
}

export const getDashboard = () => request<Dashboard>('/dashboard')
export const listQueries = () => request<{items: Array<Record<string, unknown>>; total: number}>('/queries')
export const listIngestions = () => request<{items: Array<Record<string, unknown>>; total: number}>('/billing-ingestions')
export const listFindings = () => request<{items: Array<Record<string, unknown>>; total: number}>('/findings')
export const listTickets = () => request<{items: Array<Record<string, unknown>>; total: number}>('/tickets')
export const getRecovery = () => request<{unknown_queries: number; unknown_tickets: number; requires_reconciliation: boolean}>('/recovery-status')
export const createPlan = (question: string) => request<QueryPlan>('/query-plans', { method: 'POST', body: JSON.stringify({ question, budget_limit: '10000' }) })
export const executePlan = (planId: string) => request<QueryResult>(`/query-plans/${encodeURIComponent(planId)}/execute`, { method: 'POST', body: JSON.stringify({ page_size: 100 }) })
export const createTicket = (findingId: string) => request(`/findings/${encodeURIComponent(findingId)}/tickets`, { method: 'POST', body: JSON.stringify({ approved: true }) })
export const ingestFocus = (payload: unknown) => request('/billing-ingestions', { method: 'POST', body: JSON.stringify(payload) })
