<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { api, money, today } from '../api'

const transactions = ref([])
const categories = ref([])
const accounts = ref([])
const loading = ref(true)
const searchQuery = ref('')
const selectedCategoryFilter = ref('')
const showDeactivated = ref(false)
const err = ref('')

// Dialog state
const showDialog = ref(false)
const isEditing = ref(false)
const formError = ref('')
const saving = ref(false)

// Searchable category picker state inside dialog
const showCategoryDropdown = ref(false)
const categorySearchTerm = ref('')
const categorySearchInputRef = ref(null)
const categoryDropdownRef = ref(null)

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

// Searchable category options within the Add/Edit Spend modal
const filteredActiveCategories = computed(() => {
  const term = categorySearchTerm.value.toLowerCase().trim()
  if (!term) return activeCategories.value
  return activeCategories.value.filter(c => {
    const nameMatch = (c.name || '').toLowerCase().includes(term)
    const pathMatch = (c.full_path || '').toLowerCase().includes(term)
    return nameMatch || pathMatch
  })
})

const selectedCategoryObj = computed(() => {
  if (!formData.value.category) return null
  return categories.value.find(c => Number(c.id) === Number(formData.value.category))
})

const selectedCategoryDisplay = computed(() => {
  if (!selectedCategoryObj.value) return 'No category (Uncategorised)'
  return selectedCategoryObj.value.full_path || selectedCategoryObj.value.name
})

// Duplicate prevention check:
// Checks if an active transaction already exists for a category on the selected date
function getRecordedTx(catId, targetDate = null) {
  if (!catId) return null
  const dateToCheck = targetDate || formData.value.date || today
  return transactions.value.find(tx => {
    if (isEditing.value && tx.id === formData.value.id) return false
    const txCat = tx.category || tx.spent_category
    const txDate = tx.transaction_date || tx.date
    return Number(txCat) === Number(catId) && txDate === dateToCheck && tx.is_active
  })
}

function isCategoryRecorded(catId) {
  return !!getRecordedTx(catId)
}

function isCategoryDisabled(catId) {
  return isCategoryRecorded(catId)
}

async function toggleCategoryDropdown() {
  showCategoryDropdown.value = !showCategoryDropdown.value
  if (showCategoryDropdown.value) {
    categorySearchTerm.value = ''
    await nextTick()
    if (categorySearchInputRef.value) {
      categorySearchInputRef.value.focus()
    }
  }
}

function selectCategory(catId) {
  if (catId && isCategoryDisabled(catId)) return
  formData.value.category = catId
  showCategoryDropdown.value = false
  categorySearchTerm.value = ''
  formError.value = ''
}

function clearCategory() {
  formData.value.category = ''
}

function handleClickOutside(event) {
  if (categoryDropdownRef.value && !categoryDropdownRef.value.contains(event.target)) {
    showCategoryDropdown.value = false
  }
}

// Filtered transactions for the main list
const filteredTransactions = computed(() => {
  return transactions.value.filter(tx => {
    // Inactive filter: by default, inactive spends are filtered out
    if (!showDeactivated.value && !tx.is_active) {
      return false
    }

    // Category filter
    if (selectedCategoryFilter.value) {
      const txCat = tx.category || tx.spent_category
      if (Number(txCat) !== Number(selectedCategoryFilter.value)) {
        return false
      }
    }

    // Search query filter (narrative, description, category name, full path)
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
  // Pre-select first category that is not already recorded for today
  const firstAvailable = activeCategories.value.find(c => !isCategoryRecorded(c.id, today))
  formData.value = {
    ...defaultForm(),
    category: firstAvailable ? firstAvailable.id : '',
    account: accounts.value[0]?.id || ''
  }
  categorySearchTerm.value = ''
  showCategoryDropdown.value = false
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
  categorySearchTerm.value = ''
  showCategoryDropdown.value = false
  formError.value = ''
  showDialog.value = true
}

function closeDialog() {
  showDialog.value = false
  showCategoryDropdown.value = false
  categorySearchTerm.value = ''
  formData.value = defaultForm()
}

async function saveSpend() {
  if (!formData.value.amount || Number(formData.value.amount) <= 0) {
    formError.value = 'Please enter a valid amount greater than 0.'
    return
  }

  // Duplicate restriction: restrict to one entry per category and date
  if (formData.value.category && isCategoryRecorded(formData.value.category)) {
    const existing = getRecordedTx(formData.value.category)
    const catName = selectedCategoryObj.value?.name || 'Selected category'
    const txIdText = existing ? ` (TX-${existing.id})` : ''
    formError.value = `An entry for category "${catName}" on ${formData.value.date} already exists${txIdText}. Only one entry per category and date is allowed to prevent duplicates.`
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
    const msg = e?.error || (typeof e === 'object' ? Object.values(e).flat().join(' ') : 'Failed to update transaction status')
    alert(msg)
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

onMounted(() => {
  loadData()
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

<template>
  <div class="today-spends-page">
    <!-- Page Header -->
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

    <!-- Search input -->
    <div class="search-pill-container">
      <input
        v-model="searchQuery"
        type="text"
        class="search-pill-input"
        placeholder="Search by narrative, description, spent category, or path..."
      />
    </div>

    <!-- Quick Stats Bar, Category Filter, and Toggle -->
    <div class="filters-bar">
      <div class="stat-pill">
        <span>Active Spends:</span>
        <strong class="highlight">{{ stats.active }}</strong>
      </div>
      <div class="stat-pill">
        <span>Total Spent Today:</span>
        <strong class="accent-green">{{ money(todayTotal) }}</strong>
      </div>

      <!-- Quick Category Filter Dropdown -->
      <div class="filter-pill-select">
        <label class="filter-label">Category:</label>
        <select v-model="selectedCategoryFilter" class="category-select-pill">
          <option value="">All Categories ({{ categories.length }})</option>
          <option v-for="c in categories" :key="c.id" :value="c.id">
            {{ c.full_path || c.name }}
          </option>
        </select>
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
            title="Delete transaction permanently"
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

          <!-- Searchable Spent Category Picker with duplicate prevention -->
          <div class="form-group cat-picker-container" ref="categoryDropdownRef">
            <label class="form-label between-label">
              <span>Spent Category</span>
              <span v-if="formData.category && isCategoryRecorded(formData.category)" class="badge-duplicate-warn">
                Already recorded for {{ formData.date }}
              </span>
            </label>

            <!-- Picker Trigger Display -->
            <div
              class="cat-picker-trigger"
              :class="{ 'is-open': showCategoryDropdown, 'has-error': formData.category && isCategoryRecorded(formData.category) }"
              @click="toggleCategoryDropdown"
            >
              <div class="cat-picker-content">
                <template v-if="selectedCategoryObj">
                  <div class="cat-picker-name">{{ selectedCategoryObj.name }}</div>
                  <div class="cat-picker-path">{{ selectedCategoryObj.full_path || 'No hierarchy path' }}</div>
                </template>
                <template v-else-if="formData.category === ''">
                  <div class="cat-picker-name">No category (Uncategorised)</div>
                  <div class="cat-picker-path">Miscellaneous spend without a specific category</div>
                </template>
                <span v-else class="cat-picker-placeholder">
                  Click to search & select spent category...
                </span>
              </div>
              <div class="cat-picker-actions">
                <button
                  v-if="formData.category"
                  type="button"
                  class="cat-clear-btn"
                  title="Clear category selection"
                  @click.stop="clearCategory"
                >
                  &times;
                </button>
                <span class="cat-arrow" :class="{ 'rotated': showCategoryDropdown }">&#9662;</span>
              </div>
            </div>

            <!-- Searchable Dropdown Menu -->
            <div v-if="showCategoryDropdown" class="cat-picker-menu">
              <!-- Search Input inside dropdown -->
              <div class="cat-search-box">
                <input
                  ref="categorySearchInputRef"
                  v-model="categorySearchTerm"
                  type="text"
                  class="cat-search-input"
                  placeholder="Type to search category by name or path..."
                  @click.stop
                />
                <button
                  v-if="categorySearchTerm"
                  type="button"
                  class="cat-search-clear"
                  @click.stop="categorySearchTerm = ''"
                >
                  &times;
                </button>
              </div>

              <!-- Uncategorised Option -->
              <div
                class="cat-option"
                :class="{ 'is-selected': !formData.category }"
                @click="selectCategory('')"
              >
                <div class="cat-opt-info">
                  <div class="cat-opt-name">No category (Uncategorised)</div>
                  <div class="cat-opt-path">Miscellaneous spend without a specific category</div>
                </div>
              </div>

              <!-- List of matching categories -->
              <div class="cat-options-list">
                <div
                  v-for="c in filteredActiveCategories"
                  :key="c.id"
                  class="cat-option"
                  :class="{
                    'is-selected': Number(formData.category) === Number(c.id),
                    'is-disabled': isCategoryDisabled(c.id)
                  }"
                  @click="selectCategory(c.id)"
                >
                  <div class="cat-opt-info">
                    <div class="cat-opt-name-row">
                      <span class="cat-opt-name">{{ c.name }}</span>
                      <span v-if="isCategoryRecorded(c.id)" class="badge-duplicate-warn">
                        Already recorded
                      </span>
                    </div>
                    <div class="cat-opt-path">{{ c.full_path || c.name }}</div>
                  </div>
                </div>

                <div v-if="!filteredActiveCategories.length" class="cat-no-results">
                  No categories matching "{{ categorySearchTerm }}"
                </div>
              </div>
            </div>

            <span class="form-hint">
              Select or search the granular spent category (e.g. supermarket, MEAT, milk). Duplicate entries for the same category on this date are restricted.
            </span>
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

.between-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
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

/* Category Filter Select Pill */
.filter-pill-select {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-pill);
  padding: 0.25rem 0.6rem 0.25rem 0.85rem;
  box-shadow: var(--shadow-card);
}

.filter-label {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.category-select-pill {
  background: transparent;
  border: none;
  color: var(--text-primary);
  font-size: 0.82rem;
  font-weight: 500;
  cursor: pointer;
  padding: 0.2rem 0.4rem;
  max-width: 220px;
}

.category-select-pill:focus {
  outline: none;
}

/* Searchable Category Picker */
.cat-picker-container {
  position: relative;
}

.cat-picker-trigger {
  width: 100%;
  padding: 0.65rem 0.9rem;
  background: var(--bg-input);
  border: 1px solid var(--border-input);
  border-radius: var(--radius-card);
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  transition: all 0.15s ease;
  min-height: 48px;
}

.cat-picker-trigger:hover {
  border-color: var(--accent-orange);
}

.cat-picker-trigger.is-open {
  border-color: var(--accent-orange);
  box-shadow: 0 0 0 2px rgba(255, 107, 0, 0.2);
}

.cat-picker-trigger.has-error {
  border-color: var(--text-danger);
}

.cat-picker-content {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.cat-picker-name {
  font-size: 0.92rem;
  font-weight: 600;
  color: var(--text-primary);
}

.cat-picker-path {
  font-size: 0.76rem;
  color: var(--text-muted);
}

.cat-picker-placeholder {
  color: var(--text-muted);
  font-size: 0.88rem;
}

.cat-picker-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-left: 0.5rem;
}

.cat-clear-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  font-size: 1.15rem;
  cursor: pointer;
  padding: 0 0.25rem;
  line-height: 1;
  transition: color 0.15s;
}

.cat-clear-btn:hover {
  color: var(--text-danger);
}

.cat-arrow {
  color: var(--text-muted);
  font-size: 0.8rem;
  transition: transform 0.2s ease;
}

.cat-arrow.rotated {
  transform: rotate(180deg);
}

.cat-picker-menu {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: 10px;
  box-shadow: var(--shadow-modal);
  z-index: 1000;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  max-height: 290px;
}

.cat-search-box {
  padding: 0.5rem;
  background: var(--bg-card);
  border-bottom: 1px solid var(--divider-subtle);
  position: relative;
  display: flex;
  align-items: center;
}

.cat-search-input {
  width: 100%;
  padding: 0.45rem 2rem 0.45rem 0.75rem;
  font-size: 0.85rem;
  background: var(--bg-input);
  border: 1px solid var(--border-input);
  border-radius: var(--radius-pill);
  color: var(--text-primary);
}

.cat-search-input:focus {
  outline: none;
  border-color: var(--accent-orange);
}

.cat-search-clear {
  position: absolute;
  right: 1rem;
  background: transparent;
  border: none;
  color: var(--text-muted);
  font-size: 1.1rem;
  cursor: pointer;
  padding: 0;
  line-height: 1;
}

.cat-options-list {
  overflow-y: auto;
  max-height: 220px;
}

.cat-option {
  padding: 0.6rem 0.9rem;
  cursor: pointer;
  transition: background 0.15s;
  border-bottom: 1px solid var(--divider-subtle);
}

.cat-option:last-child {
  border-bottom: none;
}

.cat-option:hover:not(.is-disabled) {
  background: var(--hover-subtle);
}

.cat-option.is-selected {
  background: rgba(255, 107, 0, 0.12);
}

.cat-option.is-disabled {
  opacity: 0.5;
  cursor: not-allowed;
  background: rgba(239, 68, 68, 0.04);
}

.cat-opt-info {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.cat-opt-name-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.5rem;
}

.cat-opt-name {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text-primary);
}

.cat-opt-path {
  font-size: 0.76rem;
  color: var(--text-muted);
}

.badge-duplicate-warn {
  font-size: 0.72rem;
  font-weight: 600;
  color: #f87171;
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.35);
  border-radius: var(--radius-pill);
  padding: 0.15rem 0.5rem;
  white-space: nowrap;
}

.cat-no-results {
  padding: 1rem;
  text-align: center;
  color: var(--text-muted);
  font-size: 0.85rem;
}

@media (max-width: 900px) {
  .tx-cols {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
