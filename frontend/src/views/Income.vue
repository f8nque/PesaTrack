<script setup>
import { ref, computed, onMounted } from 'vue'
import { api, money, today } from '../api'

const items = ref([])
const f = ref({ source: '', amount: '', date: today, recurring: false })
const load = async () => (items.value = await api('income/?month=' + today.slice(0, 7)))
async function add() {
  await api('income/', 'POST', f.value)
  f.value = { source: '', amount: '', date: today, recurring: false }; load()
}
async function del(id) { await api(`income/${id}/`, 'DELETE'); load() }
const total = computed(() => items.value.reduce((a, i) => a + Number(i.amount), 0))
onMounted(load)
</script>

<template>
  <h2>Add income</h2>
  <form class="row" @submit.prevent="add">
    <input v-model="f.source" placeholder="Source (salary, freelance...)" required />
    <input v-model="f.amount" type="number" step="0.01" min="0" placeholder="Amount" required />
    <input v-model="f.date" type="date" />
    <label><input v-model="f.recurring" type="checkbox" /> Monthly</label>
    <button class="primary">Add income</button>
  </form>
  <h2>This month <span class="muted">{{ money(total) }}</span></h2>
  <p v-if="!items.length" class="muted">No income recorded this month.</p>
  <ul>
    <li v-for="i in items" :key="i.id">
      <span>{{ i.source }}<small class="muted"> {{ i.date }}{{ i.recurring ? ', monthly' : '' }}</small></span>
      <span>{{ money(i.amount) }} <button class="link" @click="del(i.id)">Delete</button></span>
    </li>
  </ul>
</template>
