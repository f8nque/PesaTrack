<script setup>
import { ref, computed, onMounted } from 'vue'
import { api, money, today } from '../api'

const transactions = ref([])
const categories = ref([])
const accounts = ref([])
const loading = ref(true)
const searchQuery = ref('')
const showDeactivated = ref(false)
const err = ref('')

// Dialog state
const showDialog = ref(false)
const isEditing = ref(false)
const formError = ref('')
const saving = ref(false)

const defaultForm = () => ({
  id: null,
  date: today,
  category: '',
  account: '',
  amount: '',
  narrative: '',
  is_active: true
})

const formData = ref(defaultForm())

async function loadData() {
  loading.value = true
  err.value = ''
  try {
    const [txs, cats, accts] = await Promise.all([
      api(`transactions/?date=${today}`),
      api('categories/'),
      api('accounts/')
    ])
    transactions.value = txs
    categories.value = cats
    accounts.value = accts
  } catch (e) {
    err.value = 'Failed to load today\'s transactions.'
  } finally {
    loading.value = false
  }
}

// Active categories for spending
const activeCategories = computed(() => categories.value.filter(c => c.is_active))

// Filter out inactive spends unless showDeactivated is explicitly toggled on
const filteredTransactions = computed(() => {
  return transactions.value.filter(tx => {
    // Inactive filter: by default, inactive spends are filtered out
    if (!showDeactivated.value && !tx.is_active) {
      return false
    }

    // Search filter
    const q = searchQuery.value.toLowerCase().trim()
    const narrativeMatch = (tx.description || tx.narrative || '').toLowerCase().includes(q)
    const categoryName = tx.category_name || categories.value.find(c => c.id === tx.category)?.name || ''
    const catPath = tx.category_path || ''
    const catMatch = categoryName.toLowerCase().includes(q) || catPath.toLowerCase().includes(q)
    const matchesSearch = !q || narrativeMatch || catMatch

    return matchesSearch
  })
})

const todayTotal = computed(() => {
  return transactions.value
    .filter(tx => tx.is_active && tx.kind === 'expense')
    .reduce((sum, tx) => sum + Number(tx.amount || 0), 0)
})

const stats = computed(() => {
  const total = transactions.value.length
  const active = transactions.value.filter(t => t.is_active).length
  return { total, active, deactivated: total - active }
})

function getCategory(catId) {
  if (!catId) return null
  return categories.value.find(item => item.id === catId)
}

function getCategoryDisplay(tx) {
  if (tx.category_name) return tx.category_name
  const c = getCategory(tx.category)
  return c ? c.name : 'Uncategorised'
}

function getCategoryPathDisplay(tx) {
  if (tx.category_path && tx.category_path !== tx.category_name) return tx.category_path
  const c = getCategory(tx.category)
  return c && c.full_path && c.full_path !== c.name ? c.full_path : ''
}

function openAddDialog() {
  isEditing.value = false
  formData.value = {
    ...defaultForm(),
    category: activeCategories.value[0]?.id || '',
    account: accounts.value[0]?.id || ''
  }
  formError.value = ''
  showDialog.value = true
}

function openEditDialog(tx) {
  isEditing.value = true
  formData.value = {
    id: tx.id,
    date: tx.transaction_date || tx.date || today,
    category: tx.category || tx.spent_category || '',
    account: tx.account || accounts.value[0]?.id || '',
    amount: tx.amount,
    narrative: tx.description || tx.narrative || '',
    is_active: tx.is_active
  }
  formError.value = ''
  showDialog.value = true
}

function closeDialog() {
  showDialog.value = false
  formData.value = defaultForm()
}

async function saveSpend() {
  if (!formData.value.amount || Number(formData.value.amount) <= 0) {
    formError.value = 'Please enter a valid amount greater than 0.'
    return
  }

  saving.value = true
  formError.value = ''

  try {
    const payload = {
      amount: formData.value.amount,
      category: formData.value.category || null,
      account: formData.value.account || null,
      date: formData.value.date || today,
      narrative: formData.value.narrative ? formData.value.narrative.trim() : '',
      kind: 'expense'
    }

    if (isEditing.value) {
      payload.is_active = formData.value.is_active
      await api(`transactions/${formData.value.id}/`, 'PATCH', payload)
    } else {
      await api('transactions/', 'POST', payload)
    }

    closeDialog()
    await loadData()
  } catch (e) {
    formError.value = typeof e === 'object' ? Object.values(e).flat().join(' ') : 'Error saving transaction.'
  } finally {
    saving.value = false
  }
}

async function toggleActive(tx) {
  try {
    const endpoint = tx.is_active ? `transactions/${tx.id}/deactivate/` : `transactions/${tx.id}/activate/`
    await api(endpoint, 'POST')
    await loadData()
  } catch (e) {
    alert('Failed to update transaction status')
  }
}

async function deleteTx(id) {
  if (!confirm('Are you sure you want to permanently delete this transaction?')) return
  try {
    await api(`transactions/${id}/`, 'DELETE')
    await loadData()
  } catch (e) {
    alert('Failed to delete transaction.')
  }
}

function formatDisplayDate(dStr) {
  if (!dStr) return today
  const d = new Date(dStr + 'T00:00:00')
  return d.toLocaleDateString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric'
  })
}

onMounted(loadData)
</script>

<template>
  <div class="today-spends-page">
    <!-- Page Header (matching screenshot style) -->
    <div class="page-header between-header">
      <div>
        <h1 class="page-title">Today's Spends</h1>
        <p class="page-subtitle">
          Recorded transactions for <span class="tag-orange">{{ formatDisplayDate(today) }}</span>
          — Total Active: <span class="tag-green">{{ money(todayTotal) }}</span>
        </p>
      </div>
      <button class="btn-orange-pill" @click="openAddDialog">
        + Add Spend
      </button>
    </div>

    <!-- Search input (pill shaped like screenshot) -->
    <div class="search-pill-container">
      <input
        v-model="searchQuery"
        type="text"
        class="search-pill-input"
        placeholder="Search by narrative, description, spent category, or path..."
      />
    </div>

    <!-- Quick Stats Bar & Filter Toggle -->
    <div class="filters-bar">
      <div class="stat-pill">
        <span>Active Spends:</span>
        <strong class="highlight">{{ stats.active }}</strong>
      </div>
      <div class="stat-pill">
        <span>Total Spent Today:</span>
        <strong class="accent-green">{{ money(todayTotal) }}</strong>
      </div>

      <!-- Toggle to show/hide deactivated spends (hidden by default) -->
      <button
        v-if="stats.deactivated > 0"
        class="filter-btn"
        :class="{ active: showDeactivated }"
        style="margin-left: auto;"
        @click="showDeactivated = !showDeactivated"
      >
        {{ showDeactivated ? 'Hide Deactivated' : 'Show Deactivated (' + stats.deactivated + ')' }}
      </button>
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="empty-state">
      <p>Loading today's recorded spends...</p>
    </div>

    <!-- Empty State -->
    <div v-else-if="!filteredTransactions.length" class="empty-state">
      <h3>No active spends recorded for today</h3>
      <p class="muted">Click "+ Add Spend" above to record your first transaction for today.</p>
    </div>

    <!-- Clean High-Volume Data List Container -->
    <div v-else class="data-list-container">
      <div class="data-list-header tx-cols">
        <div>Narrative / Note</div>
        <div>Spent Category / Path</div>
        <div>Date</div>
        <div class="text-right">Amount</div>
        <div class="text-center">Status</div>
        <div class="text-right">Actions</div>
      </div>

      <div
        v-for="tx in filteredTransactions"
        :key="tx.id"
        class="data-row tx-cols"
        :class="{ 'is-inactive': !tx.is_active }"
      >
        <!-- Col 1: Narrative & ID -->
        <div>
          <h4 class="row-title">
            {{ tx.description || tx.narrative || getCategoryDisplay(tx) }}
          </h4>
          <div class="row-subtitle">
            <span class="accent-green">TX-{{ tx.id }}</span>
            <template v-if="tx.account_name"> &bull; {{ tx.account_name }}</template>
          </div>
        </div>

        <!-- Col 2: Category & Path -->
        <div>
          <div class="tx-cat-name">{{ getCategoryDisplay(tx) }}</div>
          <div v-if="getCategoryPathDisplay(tx)" class="tx-cat-path">
            {{ getCategoryPathDisplay(tx) }}
          </div>
        </div>

        <!-- Col 3: Date -->
        <div>
          <span class="tx-date">{{ tx.transaction_date || tx.date }}</span>
        </div>

        <!-- Col 4: Amount -->
        <div class="text-right">
          <span class="tx-amount accent-green">{{ money(tx.amount) }}</span>
        </div>

        <!-- Col 5: Status -->
        <div class="text-center">
          <span
            class="badge"
            :class="tx.is_active ? 'badge-active' : 'badge-inactive'"
          >
            {{ tx.is_active ? 'Active' : 'Deactivated' }}
          </span>
        </div>

        <!-- Col 6: Actions -->
        <div class="row-actions">
          <button
            class="btn-orange-pill"
            style="padding: 0.35rem 0.95rem; font-size: 0.82rem;"
            @click="openEditDialog(tx)"
          >
            Edit
          </button>
          <button
            class="btn-secondary-pill"
            :class="{ 'btn-danger-pill': tx.is_active }"
            style="padding: 0.35rem 0.85rem; font-size: 0.82rem;"
            @click="toggleActive(tx)"
          >
            {{ tx.is_active ? 'Deactivate' : 'Activate' }}
          </button>
          <button
            class="btn-danger-pill"
            style="padding: 0.35rem 0.85rem; font-size: 0.82rem;"
            title="Delete transaction"
            @click="deleteTx(tx.id)"
          >
            Delete
          </button>
        </div>
      </div>
    </div>

    <!-- Add / Edit Spend Modal Dialog Box -->
    <div v-if="showDialog" class="modal-overlay" @click.self="closeDialog">
      <div class="modal-dialog">
        <div class="modal-header">
          <h2 class="modal-title">
            {{ isEditing ? 'Edit Spend' : 'Add Spent' }}
          </h2>
          <button class="modal-close-btn" @click="closeDialog">&times;</button>
        </div>

        <form @submit.prevent="saveSpend">
          <!-- Date Field -->
          <div class="form-group">
            <label class="form-label">Date *</label>
            <input
              v-model="formData.date"
              type="date"
              class="form-input"
              required
            />
          </div>

          <!-- Account Dropdown -->
          <div v-if="accounts.length" class="form-group">
            <label class="form-label">Account</label>
            <select v-model="formData.account" class="form-select">
              <option v-for="a in accounts" :key="a.id" :value="a.id">
                {{ a.name }} ({{ a.kind }})
              </option>
            </select>
          </div>

          <!-- Spent Category Dropdown (displays Spent categories with hierarchy path) -->
          <div class="form-group">
            <label class="form-label">Spent Category</label>
            <select v-model="formData.category" class="form-select">
              <option value="">No category (Uncategorised)</option>
              <option
                v-for="c in activeCategories"
                :key="c.id"
                :value="c.id"
              >
                {{ c.full_path || c.name }}
              </option>
            </select>
            <span class="form-hint">Select the granular spent category (e.g. supermarket, MEAT, milk).</span>
          </div>

          <!-- Amount Field -->
          <div class="form-group">
            <label class="form-label">Amount *</label>
            <input
              v-model="formData.amount"
              type="number"
              step="0.01"
              min="0.01"
              class="form-input"
              placeholder="0.00"
              required
              autofocus
            />
          </div>

          <!-- Narrative Field -->
          <div class="form-group">
            <label class="form-label">Narrative</label>
            <input
              v-model="formData.narrative"
              type="text"
              class="form-input"
              placeholder="What did you spend on? (e.g. 2kg Beef, Weekly grocery run)"
            />
          </div>

          <!-- Active Checkbox (for edit mode) -->
          <div v-if="isEditing" class="form-group">
            <label class="form-checkbox-row">
              <input
                v-model="formData.is_active"
                type="checkbox"
              />
              <span><strong>Active spend</strong> (counts in spending and balances)</span>
            </label>
          </div>

          <!-- Error Alert -->
          <p v-if="formError" class="form-error-msg" style="color: var(--text-danger); font-size: 0.88rem; margin: 0.5rem 0;">
            {{ formError }}
          </p>

          <!-- Dialog Footer Buttons -->
          <div class="modal-footer">
            <button
              type="button"
              class="btn-secondary-pill"
              @click="closeDialog"
            >
              Cancel
            </button>
            <button
              type="submit"
              class="btn-orange-pill"
              :disabled="saving"
            >
              {{ saving ? 'Saving...' : (isEditing ? 'Save Changes' : 'Record Spend') }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.between-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 1rem;
}

.tx-cols {
  grid-template-columns: 2.2fr 1.8fr 1.1fr 1.1fr 1fr 2fr;
  gap: 1rem;
}

.tx-cat-name {
  font-size: 0.92rem;
  font-weight: 500;
  color: var(--text-primary);
}

.tx-cat-path {
  font-size: 0.78rem;
  color: var(--text-muted);
  margin-top: 0.15rem;
}

.tx-date {
  font-size: 0.88rem;
  color: var(--text-secondary);
}

.tx-amount {
  font-size: 1.05rem;
  font-weight: 700;
}

.text-right {
  text-align: right;
}

.text-center {
  text-align: center;
}

@media (max-width: 900px) {
  .tx-cols {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
