<script setup>
import { ref, computed, onMounted } from 'vue'
import { api, money } from '../api'
const kinds = ['bank', 'mpesa', 'cash', 'sacco', 'mmf', 'investment', 'credit_card']
const accts = ref([]), f = ref({ name: '', kind: 'bank', opening_balance: 0 })
const load = async () => (accts.value = await api('accounts/'))
async function add() { await api('accounts/', 'POST', f.value); f.value = { name: '', kind: 'bank', opening_balance: 0 }; load() }
async function del(id) { if (confirm('Delete this account and all its transactions?')) { await api(`accounts/${id}/`, 'DELETE'); load() } }
const total = computed(() => accts.value.reduce((a, x) => a + x.balance, 0))
onMounted(load)
</script>

<template>
  <h2>Add an account</h2>
  <form class="row" @submit.prevent="add">
    <input v-model="f.name" placeholder="Name (e.g. KCB, M-Pesa)" required />
    <select v-model="f.kind"><option v-for="k in kinds" :key="k" :value="k">{{ k.replace('_', ' ') }}</option></select>
    <input v-model="f.opening_balance" type="number" step="0.01" placeholder="Opening balance" />
    <button class="primary">Add account</button>
  </form>
  <h2>Accounts <span class="muted">{{ money(total) }}</span></h2>
  <ul>
    <li v-for="a in accts" :key="a.id">
      <span>{{ a.name }}<small class="muted">{{ a.kind.replace('_', ' ') }}</small></span>
      <span>{{ money(a.balance) }} <button class="link" @click="del(a.id)">Delete</button></span>
    </li>
  </ul>
</template>
