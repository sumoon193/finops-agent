import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import * as api from '@/api/client'
import QueryWorkbench from './QueryWorkbench.vue'

describe('query workbench', () => {
  it('requires an authorized plan before execution', async () => {
    vi.spyOn(api, 'createPlan').mockResolvedValue({
      plan_id: 'plan-1', kind: 'trend', statement: 'SELECT * FROM billing_line_item',
      ast_allowed: true, estimated_cost: '1', budget_limit: '100', status: 'planned', expires_at: 99,
    })
    vi.spyOn(api, 'executePlan').mockResolvedValue({ query_id: 'query-1', status: 'completed', page: [] })
    const wrapper = mount(QueryWorkbench)
    await wrapper.get('textarea').setValue('查看本月成本趋势')
    await wrapper.get('[data-testid="create-plan"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('SELECT * FROM billing_line_item')
    expect(wrapper.get('[data-testid="execute-plan"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-testid="execute-plan"]').trigger('click')
    await flushPromises()
    expect(api.executePlan).toHaveBeenCalledWith('plan-1')
  })
})
