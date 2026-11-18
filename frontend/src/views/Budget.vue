<script setup>
import { ref, computed, onMounted } from 'vue'
import { api, money, today } from '../api'

// Budgets list and selected budget
const budgets = ref([])
const selectedBudgetId = ref(null)
const budgetCategories = ref([])
const groupCategories = ref([])
const loading = ref(true)
const err = ref('')

// Dialog states
const showBudgetDialog = ref(false)
const isEditingBudget = ref(false)
const budgetForm = ref({
  id: null,
  name: '',
  description: '',
  start_date: today.slice(0, 8) + '01',
  end_date: today,
  allocated_amount: ''
})

const showItemDialog = ref(false)
const isEditingItem = ref(false)
const itemForm = ref({
  id: null,
  budget: null,
  budget_category: '',
  amount: '',
  reason: ''
})

const saving = ref(false)
const formError = ref('')

async function loadData() {
  loading.value = true
  err.value = ''
  try {
    const [bList, bCats, gCats] = await Promise.all([
      api('budgets/'),
      api('budget-categories/'),
      api('budget-groups/')
    ])
    budgets.value = bList
    budgetCategories.value = bCats
    groupCategories.value = gCats

    if (budgets.value.length && !selectedBudgetId.value) {
      selectedBudgetId.value = budgets.value[0].id
    }
  } catch (e) {
    err.value = 'Failed to load budget data.'
  } finally {
    loading.value = false
  }
}

const currentBudget = computed(() => {
  return budgets.value.find(b => b.id === selectedBudgetId.value) || budgets.value[0] || null
})

// Group budget items by Budget Grouping Category, sorted by Priority (1 to 10)
const groupedItems = computed(() => {
  if (!currentBudget.value || !currentBudget.value.items) return []

  const groupsMap = {}

  // Initialize from group categories to preserve priority order
  const sortedGroups = [...groupCategories.value].sort((a, b) => a.priority - b.priority)
  for (const g of sortedGroups) {
    groupsMap[g.id] = {
      id: g.id,
      name: g.name,
      priority: g.priority,
      items: [],
      totalPlanned: 0,
      totalActual: 0
    }
  }

  // Populate items into their groups
  for (const item of currentBudget.value.items) {
    const bcat = budgetCategories.value.find(b => b.id === item.budget_category)
    const grpId = bcat?.grouping
    if (grpId && groupsMap[grpId]) {
      groupsMap[grpId].items.push(item)
      groupsMap[grpId].totalPlanned += Number(item.amount || 0)
      groupsMap[grpId].totalActual += Number(item.actual_spent || 0)
    } else {
      // Fallback unassigned group
      if (!groupsMap['other']) {
        groupsMap['other'] = {
          id: 'other',
          name: 'General Expenses',
          priority: 99,
          items: [],
          totalPlanned: 0,
          totalActual: 0
        }
      }
      groupsMap['other'].items.push(item)
      groupsMap['other'].totalPlanned += Number(item.amount || 0)
      groupsMap['other'].totalActual += Number(item.actual_spent || 0)
    }
  }

  // Return groups that have items or categories
  return Object.values(groupsMap).filter(g => g.items.length > 0)
})

// Budget Dialog handlers
function openCreateBudget() {
  isEditingBudget.value = false
  formError.value = ''
  const firstDay = today.slice(0, 8) + '01'
  const lastDay = new Date(new Date().getFullYear(), new Date().getMonth() + 1, 0).toLocaleDateString('en-CA')
  budgetForm.value = {
    id: null,
    name: 'Budget ' + today.slice(0, 7),
    description: '',
    start_date: firstDay,
    end_date: lastDay,
    allocated_amount: ''
  }
  showBudgetDialog.value = true
}

function openEditBudget() {
  if (!currentBudget.value) return
  isEditingBudget.value = true
  formError.value = ''
  budgetForm.value = {
    id: currentBudget.value.id,
    name: currentBudget.value.name,
    description: currentBudget.value.description || '',
    start_date: currentBudget.value.start_date,
    end_date: currentBudget.value.end_date,
    allocated_amount: currentBudget.value.allocated_amount
  }
  showBudgetDialog.value = true
}

async function saveBudget() {
  if (!budgetForm.value.name.trim()) {
    formError.value = 'Budget name is required.'
    return
  }
  if (!budgetForm.value.allocated_amount || Number(budgetForm.value.allocated_amount) < 0) {
    formError.value = 'Please enter a valid allocated budget amount.'
    return
  }

  saving.value = true
  formError.value = ''

  try {
    const payload = {
      name: budgetForm.value.name.trim(),
      description: budgetForm.value.description.trim(),
      start_date: budgetForm.value.start_date,
      end_date: budgetForm.value.end_date,
      allocated_amount: budgetForm.value.allocated_amount
    }

    if (isEditingBudget.value) {
      const updated = await api(`budgets/${budgetForm.value.id}/`, 'PATCH', payload)
      selectedBudgetId.value = updated.id
    } else {
      const created = await api('budgets/', 'POST', payload)
      selectedBudgetId.value = created.id
    }

    showBudgetDialog.value = false
    await loadData()
  } catch (e) {
    formError.value = typeof e === 'object' ? Object.values(e).flat().join(' ') : 'Error saving budget.'
  } finally {
    saving.value = false
  }
}

// Budget Item Dialog handlers
function openAddItem() {
  if (!currentBudget.value) return
  isEditingItem.value = false
  formError.value = ''
  itemForm.value = {
    id: null,
    budget: currentBudget.value.id,
    budget_category: budgetCategories.value[0]?.id || '',
    amount: '',
    reason: ''
  }
  showItemDialog.value = true
}

function openEditItem(item) {
  isEditingItem.value = true
  formError.value = ''
  itemForm.value = {
    id: item.id,
    budget: item.budget,
    budget_category: item.budget_category,
    amount: item.amount,
    reason: item.reason || ''
  }
  showItemDialog.value = true
}

async function saveItem() {
  if (!itemForm.value.budget_category) {
    formError.value = 'Please select a Budget Category.'
    return
  }
  if (!itemForm.value.amount || Number(itemForm.value.amount) <= 0) {
    formError.value = 'Please enter a valid amount greater than 0.'
    return
  }

  saving.value = true
  formError.value = ''

  try {
    const payload = {
      budget: itemForm.value.budget,
      budget_category: itemForm.value.budget_category,
      amount: itemForm.value.amount,
      reason: itemForm.value.reason.trim()
    }

    if (isEditingItem.value) {
      await api(`budget-items/${itemForm.value.id}/`, 'PATCH', payload)
    } else {
      await api('budget-items/', 'POST', payload)
    }

    showItemDialog.value = false
    await loadData()
  } catch (e) {
    formError.value = typeof e === 'object' ? Object.values(e).flat().join(' ') : 'Error saving budget item.'
  } finally {
    saving.value = false
  }
}

async function deleteItem(id) {
  if (!confirm('Remove this budget item allocation?')) return
  try {
    await api(`budget-items/${id}/`, 'DELETE')
    await loadData()
  } catch (e) {
    alert('Failed to remove item.')
  }
}

function pct(item) {
  const planned = Number(item.amount || 0)
  const actual = Number(item.actual_spent || 0)
  if (!planned) return 0
  return Math.min(100, Math.round((actual / planned) * 100))
}

function formatDateRange(start, end) {
  if (!start || !end) return ''
  const s = new Date(start + 'T00:00:00')
  const e = new Date(end + 'T00:00:00')
  return `${s.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })} — ${e.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}`
}

onMounted(loadData)
</script>

<template>
  <div class="budget-page">
    <!-- Top Header -->
    <div class="page-header between-header">
      <div>
        <h1 class="page-title">Budget Management</h1>
        <p class="page-subtitle">
          Display organized by <span class="tag-cyan">Budget Grouping</span> (Priority 1-10) with
          <span class="tag-orange">Inputted Budget Amount</span> vs <span class="tag-green">Cumulated Items Allocation</span>
        </p>
      </div>

      <div class="header-actions">
        <!-- Budget Picker Dropdown -->
        <select
          v-if="budgets.length"
          v-model="selectedBudgetId"
          class="form-select budget-select"
        >
          <option v-for="b in budgets" :key="b.id" :value="b.id">
            {{ b.name }} ({{ b.start_date }})
          </option>
        </select>

        <button class="btn-orange-pill" @click="openCreateBudget">
          + Create Budget
        </button>
      </div>
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="empty-state">
      <p>Loading budget...</p>
    </div>

    <!-- No Budgets Yet -->
    <div v-else-if="!budgets.length" class="empty-state">
      <h3>No budgets created yet</h3>
      <p class="muted">Create your first budget to set an overall allocated amount and plan budget items.</p>
      <button class="btn-orange-pill" style="margin-top: 1rem;" @click="openCreateBudget">
        + Create First Budget
      </button>
    </div>

    <template v-else-if="currentBudget">
      <!-- Active Budget Banner -->
      <div class="budget-banner">
        <div>
          <h2 class="banner-title">{{ currentBudget.name }}</h2>
          <p class="banner-sub">
            <span>{{ formatDateRange(currentBudget.start_date, currentBudget.end_date) }}</span>
            <span v-if="currentBudget.description"> &bull; {{ currentBudget.description }}</span>
          </p>
        </div>
        <div class="banner-buttons">
          <button class="btn-secondary-pill" @click="openEditBudget">
            Edit Budget
          </button>
          <button class="btn-orange-pill" @click="openAddItem">
            + Add Budget Item
          </button>
        </div>
      </div>

      <!-- The Two Core Values & Budget Metrics Cards -->
      <div class="budget-metrics-grid">
        <!-- Value 1: Inputted Allocated Budget Amount -->
        <div class="metric-card highlight-border">
          <span class="metric-label">1. Inputted Allocated Budget</span>
          <div class="metric-value accent-orange">
            {{ money(currentBudget.allocated_amount) }}
          </div>
          <span class="metric-hint">Target ceiling amount you inputted</span>
        </div>

        <!-- Value 2: Computed Cumulated Items Allocation -->
        <div class="metric-card">
          <span class="metric-label">2. Cumulated Budget Items</span>
          <div class="metric-value accent-green">
            {{ money(currentBudget.total_item_planned) }}
          </div>
          <span class="metric-hint">Computed sum of items planned below</span>
        </div>

        <!-- Unallocated Difference -->
        <div class="metric-card">
          <span class="metric-label">Unallocated Difference</span>
          <div
            class="metric-value"
            :class="{ 'text-danger': currentBudget.unallocated_amount < 0 }"
          >
            {{ money(currentBudget.unallocated_amount) }}
          </div>
          <span class="metric-hint">
            {{ currentBudget.unallocated_amount >= 0 ? 'Remaining to allocate' : 'Over-allocated across items' }}
          </span>
        </div>

        <!-- Actual Spending Incurred -->
        <div class="metric-card">
          <span class="metric-label">Actual Spent in Period</span>
          <div class="metric-value">
            {{ money(currentBudget.actual_spent) }}
          </div>
          <span class="metric-hint">Recorded expenses in timeframe</span>
        </div>
      </div>

      <!-- Budget Section: Grouped by Budget Grouping Category (Priority 1-10) -->
      <div class="budget-display-section">
        <div class="section-title-row">
          <h2 style="margin: 0;">Budget Items Breakdown</h2>
          <span class="muted" style="font-size: 0.88rem;">
            Ordered by Grouping Priority (1: Highest &rarr; 10: Lowest)
          </span>
        </div>

        <div v-if="!groupedItems.length" class="empty-state" style="padding: 2.5rem 1rem;">
          <p class="muted">No budget items added to this budget yet.</p>
          <button class="btn-orange-pill" style="margin-top: 0.5rem;" @click="openAddItem">
            + Add First Budget Item
          </button>
        </div>

        <!-- Groups Ordered by Priority -->
        <div v-else class="groups-container">
          <div
            v-for="grp in groupedItems"
            :key="grp.id"
            class="group-card"
          >
            <!-- Group Header -->
            <div class="group-header">
              <div class="group-info">
                <span class="priority-pill" :class="'priority-' + grp.priority">
                  Priority {{ grp.priority }}
                </span>
                <h3 class="group-name">{{ grp.name }}</h3>
              </div>
              <div class="group-totals">
                <span>Planned: <strong>{{ money(grp.totalPlanned) }}</strong></span>
                <span>Actual: <strong class="accent-green">{{ money(grp.totalActual) }}</strong></span>
              </div>
            </div>

            <!-- Budget Items Rows under this Group -->
            <div class="data-list-container" style="gap: 0.4rem; padding: 0.75rem 1rem 1rem;">
              <div class="data-list-header budget-item-cols">
                <div>Budget Category</div>
                <div>Type</div>
                <div>Planned Amount</div>
                <div>Actual Spent & Progress</div>
                <div>Reason for Update</div>
                <div style="text-align: right;">Actions</div>
              </div>

              <div
                v-for="item in grp.items"
                :key="item.id"
                class="data-row budget-item-cols"
              >
                <!-- Budget Category Name -->
                <div>
                  <h4 class="row-title">{{ item.budget_category_name }}</h4>
                  <div class="row-subtitle">Item #{{ item.id }}</div>
                </div>

                <!-- Type Badge -->
                <div>
                  <span
                    class="badge"
                    :class="item.category_type === 'needs' ? 'badge-type-budget' :
                           item.category_type === 'savings' ? 'badge-savings' : 'badge-type-main'"
                  >
                    {{ item.category_type }}
                  </span>
                </div>

                <!-- Planned Amount -->
                <div>
                  <span class="amount-big" style="font-size: 1.05rem; font-weight: 700;">
                    {{ money(item.amount) }}
                  </span>
                </div>

                <!-- Actual Spent & Progress Bar -->
                <div>
                  <div style="font-size: 0.88rem; margin-bottom: 0.25rem;">
                    <span :class="{ 'text-danger': Number(item.actual_spent) > Number(item.amount) }">
                      {{ money(item.actual_spent) }}
                    </span>
                    <small class="muted">({{ pct(item) }}%)</small>
                  </div>
                  <div class="track" style="height: 6px;">
                    <i
                      :class="{ over: Number(item.actual_spent) > Number(item.amount) }"
                      :style="{ width: pct(item) + '%' }"
                    ></i>
                  </div>
                </div>

                <!-- Reason for update -->
                <div>
                  <span v-if="item.reason" class="reason-text">{{ item.reason }}</span>
                  <span v-else class="muted" style="font-size: 0.82rem; font-style: italic;">No update reason</span>
                </div>

                <!-- Actions -->
                <div class="row-actions">
                  <button
                    class="btn-orange-pill"
                    style="padding: 0.35rem 0.85rem; font-size: 0.8rem;"
                    @click="openEditItem(item)"
                  >
                    Edit
                  </button>
                  <button
                    class="btn-danger-pill"
                    style="padding: 0.35rem 0.75rem; font-size: 0.8rem;"
                    @click="deleteItem(item.id)"
                  >
                    Remove
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- ==================== CREATE / EDIT BUDGET DIALOG ==================== -->
    <div v-if="showBudgetDialog" class="modal-overlay" @click.self="showBudgetDialog = false">
      <div class="modal-dialog">
        <div class="modal-header">
          <h2 class="modal-title">{{ isEditingBudget ? 'Edit Budget' : 'Create a Budget' }}</h2>
          <button class="modal-close-btn" @click="showBudgetDialog = false">&times;</button>
        </div>

        <form @submit.prevent="saveBudget">
          <!-- Budget Name -->
          <div class="form-group">
            <label class="form-label">Budget Name *</label>
            <input
              v-model="budgetForm.name"
              class="form-input"
              placeholder="e.g. November 2026 Monthly Budget, Holiday Budget"
              required
              autofocus
            />
          </div>

          <!-- Budget Description -->
          <div class="form-group">
            <label class="form-label">Budget Description</label>
            <textarea
              v-model="budgetForm.description"
              class="form-textarea"
              rows="2"
              placeholder="e.g. Household living expenses, food and utilities"
            ></textarea>
          </div>

          <!-- Date Range: Start Date & End Date -->
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
            <div class="form-group">
              <label class="form-label">Start Date *</label>
              <input
                v-model="budgetForm.start_date"
                type="date"
                class="form-input"
                required
              />
            </div>
            <div class="form-group">
              <label class="form-label">End Date *</label>
              <input
                v-model="budgetForm.end_date"
                type="date"
                class="form-input"
                required
              />
            </div>
          </div>

          <!-- Allocated Budget Amount (Inputted) -->
          <div class="form-group">
            <label class="form-label">Allocated Budget Amount *</label>
            <input
              v-model="budgetForm.allocated_amount"
              type="number"
              step="0.01"
              min="0"
              class="form-input"
              placeholder="e.g. 75000.00"
              required
            />
            <span class="form-hint">
              This acts as your overall allocated budget amount (distinct from cumulated budget items).
            </span>
          </div>

          <!-- Error Alert -->
          <p v-if="formError" class="form-error-msg" style="color: var(--text-danger); font-size: 0.88rem; margin: 0.5rem 0;">
            {{ formError }}
          </p>

          <!-- Footer Buttons -->
          <div class="modal-footer">
            <button type="button" class="btn-secondary-pill" @click="showBudgetDialog = false">
              Cancel
            </button>
            <button type="submit" class="btn-orange-pill" :disabled="saving">
              {{ saving ? 'Saving...' : (isEditingBudget ? 'Save Changes' : 'Create Budget') }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- ==================== ADD / EDIT BUDGET ITEM DIALOG ==================== -->
    <div v-if="showItemDialog" class="modal-overlay" @click.self="showItemDialog = false">
      <div class="modal-dialog">
        <div class="modal-header">
          <h2 class="modal-title">{{ isEditingItem ? 'Edit Budget Item' : 'Add Budget Item' }}</h2>
          <button class="modal-close-btn" @click="showItemDialog = false">&times;</button>
        </div>

        <form @submit.prevent="saveItem">
          <!-- Linked Budget Category -->
          <div class="form-group">
            <label class="form-label">Linked Budget Category *</label>
            <select
              v-model="itemForm.budget_category"
              class="form-select"
              required
              :disabled="isEditingItem"
            >
              <option value="" disabled>Select Budget Category</option>
              <option
                v-for="c in budgetCategories"
                :key="c.id"
                :value="c.id"
              >
                {{ c.name }} ({{ c.grouping_name }} &bull; Priority: {{ c.grouping_priority }})
              </option>
            </select>
            <span class="form-hint">Budget items link directly to a Budget Category.</span>
          </div>

          <!-- Amount -->
          <div class="form-group">
            <label class="form-label">Planned Amount *</label>
            <input
              v-model="itemForm.amount"
              type="number"
              step="0.01"
              min="0.01"
              class="form-input"
              placeholder="0.00"
              required
              autofocus
            />
          </div>

          <!-- Reason for update -->
          <div class="form-group">
            <label class="form-label">Reason for Update</label>
            <input
              v-model="itemForm.reason"
              type="text"
              class="form-input"
              placeholder="e.g. Increased allocation for school holiday visitors, fuel price hike"
            />
            <span class="form-hint">Records the justification or note for this allocation or change.</span>
          </div>

          <!-- Error Alert -->
          <p v-if="formError" class="form-error-msg" style="color: var(--text-danger); font-size: 0.88rem; margin: 0.5rem 0;">
            {{ formError }}
          </p>

          <!-- Footer Buttons -->
          <div class="modal-footer">
            <button type="button" class="btn-secondary-pill" @click="showItemDialog = false">
              Cancel
            </button>
            <button type="submit" class="btn-orange-pill" :disabled="saving">
              {{ saving ? 'Saving...' : (isEditingItem ? 'Save Changes' : 'Add Item') }}
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

.header-actions {
  display: flex;
  gap: 0.75rem;
  align-items: center;
  flex-wrap: wrap;
}

.budget-select {
  padding: 0.5rem 1rem;
  background: var(--bg-card);
  border: 1px solid var(--border-input);
  border-radius: var(--radius-pill);
  color: var(--text-primary);
  font-size: 0.9rem;
}

/* Banner */
.budget-banner {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-card);
  padding: 1.25rem 1.75rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
  flex-wrap: wrap;
  gap: 1rem;
}

.banner-title {
  margin: 0 0 0.25rem;
  font-size: 1.35rem;
  font-weight: 700;
  color: var(--text-primary);
}

.banner-sub {
  margin: 0;
  color: var(--text-secondary);
  font-size: 0.88rem;
}

.banner-buttons {
  display: flex;
  gap: 0.75rem;
}

/* Metrics Grid: The Two Core Values */
.budget-metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 1.25rem;
  margin-bottom: 2rem;
}

.metric-card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-card);
  padding: 1.25rem 1.4rem;
  display: flex;
  flex-direction: column;
}

.metric-card.highlight-border {
  border-color: rgba(255, 107, 0, 0.45);
  box-shadow: 0 4px 15px rgba(255, 107, 0, 0.08);
}

.metric-label {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 0.4rem;
}

.metric-value {
  font-size: 1.6rem;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.02em;
  margin-bottom: 0.25rem;
}

.metric-value.accent-orange {
  color: var(--accent-orange);
}

.metric-value.accent-green {
  color: var(--text-green);
}

.metric-hint {
  font-size: 0.78rem;
  color: var(--text-muted);
}

/* Budget Display Section */
.budget-display-section {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.section-title-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.groups-container {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.group-card {
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-card);
  overflow: hidden;
}

.group-header {
  background: rgba(255, 255, 255, 0.03);
  padding: 0.85rem 1.25rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--border-card);
  flex-wrap: wrap;
  gap: 0.75rem;
}

.group-info {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.group-name {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--text-primary);
}

.group-totals {
  display: flex;
  gap: 1.25rem;
  font-size: 0.9rem;
  color: var(--text-secondary);
}

.budget-item-cols {
  grid-template-columns: 2fr 1fr 1.3fr 1.6fr 1.8fr 1.3fr;
  gap: 1rem;
}

.reason-text {
  font-size: 0.85rem;
  color: var(--text-secondary);
  background: rgba(255, 255, 255, 0.03);
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  display: inline-block;
}

/* Priority styling */
.priority-pill {
  display: inline-flex;
  align-items: center;
  padding: 0.15rem 0.6rem;
  border-radius: var(--radius-pill);
  font-size: 0.75rem;
  font-weight: 700;
}

.priority-1, .priority-2 {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
  border: 1px solid rgba(239, 68, 68, 0.35);
}

.priority-3, .priority-4, .priority-5 {
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
  border: 1px solid rgba(245, 158, 11, 0.35);
}

.priority-6, .priority-7, .priority-8, .priority-9, .priority-10 {
  background: rgba(56, 189, 248, 0.15);
  color: #38bdf8;
  border: 1px solid rgba(56, 189, 248, 0.35);
}

@media (max-width: 900px) {
  .budget-item-cols {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
