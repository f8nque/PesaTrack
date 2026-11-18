<script setup>
import { ref, computed, onMounted } from 'vue'
import { api, money, today, month, label } from '../api'

const items = ref([])
const accts = ref([])
const cats = ref([])
const err = ref('')

const blank = () => ({
  kind: 'expense',
  account: '',
  to_account: '',
  category: '',
  amount: '',
  fee: '',
  description: '',
  transaction_date: today
})
const f = ref(blank())

async function load() {
  ;[items.value, accts.value, cats.value] = await Promise.all([
    api('transactions/?month=' + month),
    api('accounts/?include_archived=true'),
    api('categories/')
  ])

  // Pre-select primary default account
  if (!f.value.account) {
    const defaultAcct = accts.value.find(a => a.is_default && !a.is_archived)
      || accts.value.find(a => !a.is_archived)
      || accts.value[0]
    if (defaultAcct) f.value.account = defaultAcct.id
  }
}

// Active accounts for new transactions (excluding archived)
const activeAccounts = computed(() => accts.value.filter(a => !a.is_archived))

const selectedAccountObj = computed(() => {
  return accts.value.find(a => a.id === f.value.account)
})

const totalDeductionPreview = computed(() => {
  const amt = Number(f.value.amount) || 0
  const fee = Number(f.value.fee) || 0
  return amt + fee
})

const willBreachMinimum = computed(() => {
  if (!selectedAccountObj.value) return false
  const min = Number(selectedAccountObj.value.minimum_balance) || 0
  if (min <= 0) return false
  if (f.value.kind === 'income') return false
  const current = Number(selectedAccountObj.value.balance) || 0
  return (current - totalDeductionPreview.value) < min
})

async function add() {
  err.value = ''
  try {
    const b = { ...f.value }
    for (const k of ['to_account', 'category']) b[k] = b[k] || null
    b.fee = b.fee === '' ? 0 : Number(b.fee)
    b.amount = Number(b.amount)
    await api('transactions/', 'POST', b)
    f.value = { ...blank(), kind: f.value.kind, account: f.value.account }
    await load()
  } catch (e) {
    err.value = typeof e === 'object' ? Object.values(e).flat().join(' ') : 'Failed to record transaction.'
  }
}

async function del(id) {
  if (confirm('Delete this transaction?')) {
    await api(`transactions/${id}/`, 'DELETE')
    await load()
  }
}

const name = id => accts.value.find(a => a.id === id)?.name
const catOpts = computed(() => cats.value.map(c => ({ id: c.id, text: label({ ...c, parentName: cats.value.find(p => p.id === c.parent)?.name }) })))
const catText = id => catOpts.value.find(c => c.id === id)?.text
const sign = t => (t.kind === 'income' || (t.kind === 'adjustment' && t.adjustment_type === 'credit') ? '+' : (t.kind === 'expense' || (t.kind === 'adjustment' && t.adjustment_type === 'debit') ? '-' : ''))

onMounted(load)
</script>

<template>
  <div class="transactions-view">
    <header class="page-header">
      <h1 class="page-title">Transactions</h1>
      <p class="page-subtitle">Record daily expenses, incomes, tariff fees, and account transfers.</p>
    </header>

    <p v-if="!activeAccounts.length" class="empty-state">
      Add an account first (Accounts tab), then record transactions here.
    </p>

    <div v-else>
      <form class="row" style="align-items: flex-start;" @submit.prevent="add">
        <select v-model="f.kind">
          <option value="expense">Expense</option>
          <option value="income">Income</option>
          <option value="transfer">Transfer</option>
        </select>

        <select v-model="f.account" required>
          <option value="" disabled>Select {{ f.kind === 'transfer' ? 'from ' : '' }}account</option>
          <option v-for="a in activeAccounts" :key="a.id" :value="a.id">
            {{ f.kind === 'transfer' ? 'From ' : '' }}{{ a.name }} ({{ money(a.balance) }})
          </option>
        </select>

        <select v-if="f.kind === 'transfer'" v-model="f.to_account" required>
          <option value="" disabled>To account</option>
          <option v-for="a in activeAccounts" :key="a.id" :value="a.id" :disabled="a.id === f.account">
            {{ a.name }} ({{ money(a.balance) }})
          </option>
        </select>

        <select v-else-if="f.kind === 'expense'" v-model="f.category">
          <option value="">No category</option>
          <option v-for="c in catOpts" :key="c.id" :value="c.id">{{ c.text }}</option>
        </select>

        <input v-model="f.amount" type="number" step="0.01" min="0.01" placeholder="Amount" required />

        <input
          v-if="f.kind === 'transfer' || f.kind === 'expense'"
          v-model="f.fee"
          type="number"
          step="0.01"
          min="0"
          placeholder="Tariff / Fee (optional)"
          title="Bank or M-Pesa transaction fee"
        />

        <input v-model="f.description" placeholder="Description / Narrative" />
        <input v-model="f.transaction_date" type="date" />
        <button class="primary">Add {{ f.kind }}</button>
      </form>

      <!-- Low Balance & Fee notices -->
      <div v-if="willBreachMinimum" class="low-balance-alert-banner" style="margin-bottom: 1rem;">
        ⚠️ Warning: This entry will drop {{ selectedAccountObj.name }} below its minimum safety balance of {{ money(selectedAccountObj.minimum_balance) }}.
      </div>

      <div v-if="Number(f.fee) > 0" class="transfer-preview-box" style="margin-bottom: 1rem;">
        <span>
          Total deducted from <strong>{{ selectedAccountObj?.name || 'Account' }}</strong>:
          <strong class="neg">{{ money(totalDeductionPreview) }}</strong> (Amount: {{ money(f.amount || 0) }} + Fee: {{ money(f.fee) }})
        </span>
      </div>
    </div>

    <p v-if="err" class="neg" style="margin: 0.5rem 0;">{{ err }}</p>

    <h2 style="margin-top: 2rem;">Transactions This Month</h2>
    <p v-if="!items.length" class="muted">No transactions this month.</p>
    <ul v-else>
      <li v-for="t in items" :key="t.id">
        <div>
          <strong>{{ t.narrative || t.description || catText(t.category) || t.kind }}</strong>
          <small class="muted">
            {{ t.date || t.transaction_date }},
            <template v-if="t.kind === 'transfer'">
              {{ name(t.account) }} ➔ {{ name(t.to_account) }}
            </template>
            <template v-else-if="t.kind === 'adjustment'">
              Reconciliation for {{ name(t.account) }}
            </template>
            <template v-else>
              {{ name(t.account) }}
            </template>
            <template v-if="Number(t.fee) > 0"> &bull; Tariff: {{ money(t.fee) }}</template>
          </small>
        </div>

        <div class="between" style="gap: 1rem;">
          <span :class="{ neg: t.kind === 'expense' || (t.kind === 'adjustment' && t.adjustment_type === 'debit'), 'tag-green': t.kind === 'income' || (t.kind === 'adjustment' && t.adjustment_type === 'credit') }">
            {{ sign(t) }}{{ money(t.amount) }}
          </span>
          <button class="link" style="color: var(--text-danger);" @click="del(t.id)">Delete</button>
        </div>
      </li>
    </ul>
  </div>
</template>