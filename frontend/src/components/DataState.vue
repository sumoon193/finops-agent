<script setup lang="ts">
import { AlertTriangle, Inbox, RefreshCw } from 'lucide-vue-next'
defineProps<{ error?: boolean; title: string; detail: string }>()
defineEmits<{ retry: [] }>()
</script>
<template><div class="data-state" role="alert"><component :is="error ? AlertTriangle : Inbox" :size="20"/><div><strong>{{ title }}</strong><p>{{ detail }}</p></div><button v-if="error" class="quiet-button" @click="$emit('retry')"><RefreshCw :size="15"/>重试</button></div></template>
