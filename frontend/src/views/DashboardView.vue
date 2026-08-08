<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { CircleDollarSign, FileInput, Search, TriangleAlert } from 'lucide-vue-next'
import { getDashboard, listQueries, type Dashboard } from '@/api/client'
import DataState from '@/components/DataState.vue'
const data=ref<Dashboard>(); const queries=ref<Array<Record<string,unknown>>>([]); const error=ref(false)
const metrics=computed(()=>[
 {label:'账单金额',value:data.value?`¥ ${data.value.total_amount}`:'—',icon:CircleDollarSign},
 {label:'账单行',value:data.value?.billing_lines??'—',icon:FileInput},
 {label:'查询任务',value:data.value?.query_runs??'—',icon:Search},
 {label:'开放异常',value:data.value?.open_findings??'—',icon:TriangleAlert},
])
async function load(){error.value=false;try{const [d,q]=await Promise.all([getDashboard(),listQueries()]);data.value=d;queries.value=q.items}catch{error.value=true}}
onMounted(load)
</script>
<template><div class="page"><DataState v-if="error" error title="成本数据不可用" detail="请检查身份、API 和 PostgreSQL。" @retry="load"/><template v-else><section class="metric-strip"><article v-for="m in metrics" :key="m.label"><component :is="m.icon" :size="18"/><span>{{m.label}}</span><strong>{{m.value}}</strong></article></section><section class="panel"><header><div><p class="kicker">RECENT EXECUTIONS</p><h2>最近查询</h2></div><RouterLink to="/query">新建查询</RouterLink></header><DataState v-if="queries.length===0" title="暂无查询任务" detail="通过自然语言生成受控查询计划后，执行记录会出现在这里。"/><table v-else><thead><tr><th>查询 ID</th><th>状态</th><th>语句</th></tr></thead><tbody><tr v-for="q in queries" :key="String(q.query_id)"><td class="mono">{{q.query_id}}</td><td><span class="badge" :data-state="q.status">{{q.status}}</span></td><td class="mono">{{q.statement}}</td></tr></tbody></table></section></template></div></template>
