<script setup>
import { ref, onMounted } from 'vue'
import { api, money, monthStart } from '../api'

const cats = ref([]), budgets = ref([])
const name = ref(''), b = ref({ category: '', limit: '' })

async function load() {
  cats.value = await api('categories/')
  budgets.value = (await api('summary/')).budgets
}
async function addCat() { await api('categories/', 'POST', { name: name.value }); name.value = ''; load() }
async function setBudget() {
  await api('budgets/', 'POST', { ...b.value, month: monthStart })
  b.value = { category: '', limit: '' }; load()
}
async function del(id) { await api(`budgets/${id}/`, 'DELETE'); load() }
const pct = x => Math.min(100, (x.spent / x.limit) * 100)
onMounted(load)
</script>

<template>
  <h2>Categories</h2>
  <form class="row" @submit.prevent="addCat">
    <input v-model="name" placeholder="e.g. Groceries" required />
    <button class="primary">Add category</button>
  </form>
  <p class="muted">{{ cats.map(c => c.name).join(', ') || 'No categories yet.' }}</p>

  <h2>This month's budget</h2>
  <form class="row" @submit.prevent="setBudget">
    <select v-model="b.category" required>
      <option value="" disabled>Category</option>
      <option v-for="c in cats" :key="c.id" :value="c.id">{{ c.name }}</option>
    </select>
    <input v-model="b.limit" type="number" step="0.01" min="0" placeholder="Limit" required />
    <button class="primary">Set budget</button>
  </form>
  <ul>
    <li v-for="x in budgets" :key="x.id" class="stack">
      <div class="between"><strong>{{ x.name }}</strong>
        <span :class="{ neg: x.spent > x.limit }">{{ money(x.spent) }} of {{ money(x.limit) }}</span></div>
      <div class="track"><i :class="{ over: x.spent > x.limit }" :style="{ width: pct(x) + '%' }"></i></div>
      <button class="link" @click="del(x.id)">Remove</button>
    </li>
  </ul>
</template>
