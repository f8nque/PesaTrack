<script setup>
import { ref, onMounted } from 'vue'
import { api, money } from '../api'
const s = ref(null)
onMounted(async () => (s.value = await api('summary/')))
const pct = b => Math.min(100, b.planned ? (b.actual / b.planned) * 100 : 0)
</script>

<template>
  <template v-if="s">
    <p class="muted">Left this month</p>
    <p class="big" :class="{ neg: s.left < 0 }">{{ money(s.left) }}</p>
    <div class="facts">
      <span>Income {{ money(s.income) }}</span><span>Spent {{ money(s.spent) }}</span>
      <span>Debt repaid {{ money(s.debt_paid) }}</span><span>Savings rate {{ s.savings_rate }}%</span>
    </div>
    <div class="facts">
      <span>Spent today {{ money(s.today_spent) }}</span><span>Unallocated {{ money(s.unallocated) }}</span>
      <span>All accounts {{ money(s.total_balance) }}</span><span>Debt owed {{ money(s.debt_balance) }}</span>
    </div>
    <h2>Budget remaining</h2>
    <p v-if="!s.budget.length" class="muted">No budget for this month. Set one in the Budget tab.</p>
    <ul>
      <li v-for="b in s.budget" :key="b.id" class="stack">
        <div class="between"><strong>{{ b.name }}</strong>
          <span :class="{ neg: b.actual > b.planned }">{{ money(b.planned - b.actual) }} left of {{ money(b.planned) }}</span></div>
        <div class="track"><i :class="{ over: b.actual > b.planned }" :style="{ width: pct(b) + '%' }"></i></div>
      </li>
    </ul>
  </template>
</template>
