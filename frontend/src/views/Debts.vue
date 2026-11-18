<script setup>
import { ref, onMounted } from 'vue'
import { api, money, today } from '../api'

const debts = ref([]), accts = ref([]), pay = ref({}), from = ref('')
const blank = () => ({ name: '', principal: '', interest_rate: 0, min_payment: 0 })
const f = ref(blank())
async function load() {
  ;[debts.value, accts.value] = await Promise.all([api('debts/'), api('accounts/')])
  if (!from.value && accts.value.length) from.value = accts.value[0].id
}
async function add() { await api('debts/', 'POST', f.value); f.value = blank(); load() }
async function repay(d) {
  await api('transactions/', 'POST', { kind: 'expense', account: from.value, debt: d.id, amount: pay.value[d.id], transaction_date: today, description: 'Repayment: ' + d.name })
  pay.value[d.id] = ''; load()
}
async function del(id) { await api(`debts/${id}/`, 'DELETE'); load() }
const paidPct = d => Math.max(0, Math.min(100, ((d.principal - d.balance) / d.principal) * 100))
onMounted(load)
</script>

<template>
  <h2>Add a debt</h2>
  <form class="row" @submit.prevent="add">
    <input v-model="f.name" placeholder="Name (e.g. Car loan)" required />
    <input v-model="f.principal" type="number" step="0.01" min="0" placeholder="Amount owed" required />
    <input v-model="f.interest_rate" type="number" step="0.01" min="0" placeholder="Interest % per year" />
    <input v-model="f.min_payment" type="number" step="0.01" min="0" placeholder="Minimum payment" />
    <button class="primary">Add debt</button>
  </form>

  <h2>Debts</h2>
  <p v-if="!debts.length" class="muted">No debts recorded.</p>
  <p v-else-if="!accts.length" class="muted">Add an account first, so repayments come out of somewhere.</p>
  <ul>
    <li v-for="d in debts" :key="d.id" class="stack">
      <div class="between"><strong>{{ d.name }}</strong><span>{{ money(d.balance) }} left of {{ money(d.principal) }}</span></div>
      <div class="track"><i :style="{ width: paidPct(d) + '%' }"></i></div>
      <form class="row" @submit.prevent="repay(d)">
        <select v-model="from"><option v-for="a in accts" :key="a.id" :value="a.id">Pay from {{ a.name }}</option></select>
        <input v-model="pay[d.id]" type="number" step="0.01" min="0" :placeholder="'Repayment (min ' + money(d.min_payment) + ')'" required />
        <button class="primary">Record repayment</button>
        <button type="button" class="link" @click="del(d.id)">Delete debt</button>
      </form>
    </li>
  </ul>
</template>
