<script setup lang="ts">
import { onMounted, ref } from 'vue'
import Papa from 'papaparse'
import { FileUp } from 'lucide-vue-next'
import { ingestFocus, listIngestions } from '@/api/client'
import DataState from '@/components/DataState.vue'

type CsvRow = Record<string, string>
const rows=ref<Array<Record<string,unknown>>>([]);const busy=ref(false);const error=ref('')
async function load(){try{rows.value=(await listIngestions()).items}catch(e){error.value=(e as Error).message}}
function pick(row:CsvRow,...keys:string[]){for(const key of keys){if(row[key])return row[key]}return''}
async function selectFile(event:Event){const file=(event.target as HTMLInputElement).files?.[0];if(!file)return;busy.value=true;error.value='';try{const parsed=await new Promise<Papa.ParseResult<CsvRow>>((resolve,reject)=>Papa.parse<CsvRow>(file,{header:true,skipEmptyLines:true,complete:resolve,error:reject}));if(parsed.errors.length)throw new Error(parsed.errors[0].message);const watermark=new Date().toISOString();const raw_lines=parsed.data.map((row,index)=>({source_id:pick(row,'ChargePeriodStart','BillingPeriodStart')||`${file.name}-${index+1}`,currency:pick(row,'BillingCurrency','Currency')||'CNY',unit:'yuan',amount:pick(row,'BilledCost','EffectiveCost','ListCost','Amount')||'0',watermark,raw_ref:`focus://${file.name}#${index+2}`}));await ingestFocus({watermark,raw_lines});await load()}catch(e){error.value=(e as Error).message}finally{busy.value=false}}
onMounted(load)
</script>
<template><div class="page"><section class="panel"><header><div><p class="kicker">FOCUS DATASET</p><h2>账单导入</h2></div><label class="primary-button"><FileUp :size="17"/>{{busy?'导入中':'选择 CSV'}}<input hidden type="file" accept=".csv,text/csv" :disabled="busy" @change="selectFile"/></label></header><p v-if="error" class="error-line" role="alert">{{error}}</p><DataState v-if="!error&&rows.length===0" title="暂无账单数据" detail="导入 FOCUS CSV 后，服务端会规范化并写入受信账单存储。"/><div v-else class="result-scroll"><table><thead><tr><th>来源</th><th>金额</th><th>币种</th><th>水位线</th><th>溯源</th></tr></thead><tbody><tr v-for="row in rows" :key="String(row.billing_line_id)"><td>{{row.source_id}}</td><td>{{row.amount}}</td><td>{{row.currency}}</td><td>{{row.watermark}}</td><td class="mono">{{row.raw_ref}}</td></tr></tbody></table></div></section></div></template>
