<script setup>
import { ref, computed, onMounted } from 'vue'
import { api, money, today, month, label } from '../api'

const items = ref([]), accts = ref([]), cats = ref([]), err = ref('')
const blank = () => ({ kind: 'expense', account: '', to_account: '', category: '', amount: '', description: '', transaction_date: today })
const f = ref(blank())

async function load() {
  ;[items.value, accts.value, cats.value] = await Promise.all([api('transactions/?month=' + month), api('accounts/'), api('categories/')])
  if (!f.value.account && accts.value.length) f.value.account = accts.value[0].id
}
async function add() {
  err.value = ''
  try {
    const b = { ...f.value }
    for (const k of ['to_account', 'category']) b[k] = b[k] || null
    await api('transactions/', 'POST', b)
    f.value = { ...blank(), kind: f.value.kind, account: f.value.account }
    load()
  } catch (e) { err.value = Object.values(e).flat().join(' ') }
}
async function del(id) { await api(`transactions/${id}/`, 'DELETE'); load() }
const name = id => accts.value.find(a => a.id === id)?.name
const catOpts = computed(() => cats.value.map(c => ({ id: c.id, text: label({ ...c, parentName: cats.value.find(p => p.id === c.parent)?.name }) })))
const catText = id => catOpts.value.find(c => c.id === id)?.text
const sign = t => (t.kind === 'income' ? '+' : t.kind === 'expense' ? '-' : '')
onMounted(load)
</script>

<template>
  <p v-if="!accts.length" class="muted">Add an account first (Accounts tab), then record transactions here.</p>
  <form v-else class="row" @submit.prevent="add">
    <select v-model="f.kind"><option value="expense">Expense</option><option value="income">Income</option><option value="transfer">Transfer</option></select>
    <select v-model="f.account"><option v-for="a in accts" :key="a.id" :value="a.id">{{ f.kind === 'transfer' ? 'From ' : '' }}{{ a.name }}</option></select>
    <select v-if="f.kind === 'transfer'" v-model="f.to_account" required>
      <option value="" disabled>To account</option><option v-for="a in accts" :key="a.id" :value="a.id">{{ a.name }}</option>
    </select>
    <select v-else-if="f.kind === 'expense'" v-model="f.category">
      <option value="">No category</option><option v-for="c in catOpts" :key="c.id" :value="c.id">{{ c.text }}</option>
    </select>
    <input v-model="f.amount" type="number" step="0.01" min="0" placeholder="Amount" required />
    <input v-model="f.description" placeholder="Description" />
    <input v-model="f.transaction_date" type="date" />
    <button class="primary">Add {{ f.kind }}</button>
  </form>
  <p v-if="err" class="neg">{{ err }}</p>

  <h2>This month</h2>
  <p v-if="!items.length" class="muted">No transactions this month.</p>
  <ul>
    <li v-for="t in items" :key="t.id">
      <span>{{ t.description || catText(t.category) || t.kind }}
        <small class="muted">{{ t.transaction_date }}, {{ name(t.account) }}{{ t.kind === 'transfer' ? ' to ' + name(t.to_account) : '' }}</small></span>
      <span :class="{ neg: t.kind === 'expense' }">{{ sign(t) }}{{ money(t.amount) }} <button class="link" @click="del(t.id)">Delete</button></span>
    </li>
  </ul>
</template>
