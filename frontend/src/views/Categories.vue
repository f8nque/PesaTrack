<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'

// Sub-navigation: 3 category links
// 'grouping' | 'budget' | 'spent'
const currentTab = ref('grouping')

// Data collections
const groupCategories = ref([])
const budgetCategories = ref([])
const spentCategories = ref([])
const loading = ref(true)
const searchQuery = ref('')
const err = ref('')

// Dialog state
const showDialog = ref(false)
const isEditing = ref(false)
const formError = ref('')
const saving = ref(false)

// Form states for each tier
const groupForm = ref({ id: null, name: '', priority: 1 })
const budgetForm = ref({ id: null, name: '', grouping: '', category_type: 'needs', is_active: true })
const spentForm = ref({ id: null, name: '', budget_category: '', is_savings: false, is_active: true, created_at: null })

async function loadAll() {
  loading.value = true
  err.value = ''
  try {
    const [groups, bCats, sCats] = await Promise.all([
      api('budget-groups/'),
      api('budget-categories/'),
      api('spent-categories/')
    ])
    groupCategories.value = groups
    budgetCategories.value = bCats
    spentCategories.value = sCats
  } catch (e) {
    err.value = 'Failed to load category data.'
  } finally {
    loading.value = false
  }
}

// Filtered lists
const filteredGroups = computed(() => {
  const q = searchQuery.value.toLowerCase().trim()
  return groupCategories.value.filter(g => !q || g.name.toLowerCase().includes(q))
})

const filteredBudgetCats = computed(() => {
  const q = searchQuery.value.toLowerCase().trim()
  return budgetCategories.value.filter(b => {
    const nameMatch = b.name.toLowerCase().includes(q)
    const grpMatch = (b.grouping_name || '').toLowerCase().includes(q)
    return !q || nameMatch || grpMatch
  })
})

const filteredSpentCats = computed(() => {
  const q = searchQuery.value.toLowerCase().trim()
  return spentCategories.value.filter(s => {
    const nameMatch = s.name.toLowerCase().includes(q)
    const pathMatch = (s.full_path || '').toLowerCase().includes(q)
    return !q || nameMatch || pathMatch
  })
})

// Dialog openers
function openCreateDialog() {
  isEditing.value = false
  formError.value = ''

  if (currentTab.value === 'grouping') {
    groupForm.value = { id: null, name: '', priority: (groupCategories.value.length % 10) + 1 }
  } else if (currentTab.value === 'budget') {
    budgetForm.value = {
      id: null,
      name: '',
      grouping: groupCategories.value[0]?.id || '',
      category_type: 'needs',
      is_active: true
    }
  } else {
    spentForm.value = {
      id: null,
      name: '',
      budget_category: budgetCategories.value[0]?.id || '',
      is_savings: false,
      is_active: true,
      created_at: null
    }
  }
  showDialog.value = true
}

function openEditDialog(item) {
  isEditing.value = true
  formError.value = ''

  if (currentTab.value === 'grouping') {
    groupForm.value = { id: item.id, name: item.name, priority: item.priority }
  } else if (currentTab.value === 'budget') {
    budgetForm.value = {
      id: item.id,
      name: item.name,
      grouping: item.grouping,
      category_type: item.category_type || 'needs',
      is_active: !!item.is_active
    }
  } else {
    spentForm.value = {
      id: item.id,
      name: item.name,
      budget_category: item.budget_category || '',
      is_savings: !!item.is_savings,
      is_active: !!item.is_active,
      created_at: item.created_at
    }
  }
  showDialog.value = true
}

function closeDialog() {
  showDialog.value = false
}

// Save handler
async function saveItem() {
  saving.value = true
  formError.value = ''

  try {
    if (currentTab.value === 'grouping') {
      if (!groupForm.value.name.trim()) throw { error: 'Grouping name is required.' }
      const payload = { name: groupForm.value.name.trim(), priority: Number(groupForm.value.priority) }
      if (isEditing.value) {
        await api(`budget-groups/${groupForm.value.id}/`, 'PATCH', payload)
      } else {
        await api('budget-groups/', 'POST', payload)
      }
    } else if (currentTab.value === 'budget') {
      if (!budgetForm.value.name.trim()) throw { error: 'Budget category name is required.' }
      if (!budgetForm.value.grouping) throw { error: 'Please link to a Budget Grouping Category.' }
      const payload = {
        name: budgetForm.value.name.trim(),
        grouping: budgetForm.value.grouping,
        category_type: budgetForm.value.category_type,
        is_active: budgetForm.value.is_active
      }
      if (isEditing.value) {
        await api(`budget-categories/${budgetForm.value.id}/`, 'PATCH', payload)
      } else {
        await api('budget-categories/', 'POST', payload)
      }
    } else {
      if (!spentForm.value.name.trim()) throw { error: 'Spent category name is required.' }
      const payload = {
        name: spentForm.value.name.trim(),
        budget_category: spentForm.value.budget_category || null,
        is_savings: spentForm.value.is_savings,
        is_active: spentForm.value.is_active
      }
      if (isEditing.value) {
        await api(`spent-categories/${spentForm.value.id}/`, 'PATCH', payload)
      } else {
        await api('spent-categories/', 'POST', payload)
      }
    }

    closeDialog()
    await loadAll()
  } catch (e) {
    formError.value = typeof e === 'object' ? Object.values(e).flat().join(' ') : 'Error saving category.'
  } finally {
    saving.value = false
  }
}

// Delete / Deactivate handler
async function deleteItem(id) {
  if (!confirm('Are you sure you want to delete this category?')) return
  try {
    if (currentTab.value === 'grouping') {
      await api(`budget-groups/${id}/`, 'DELETE')
    } else if (currentTab.value === 'budget') {
      await api(`budget-categories/${id}/`, 'DELETE')
    } else {
      await api(`spent-categories/${id}/`, 'DELETE')
    }
    await loadAll()
  } catch (e) {
    alert('Failed to delete category.')
  }
}

async function toggleActive(item, type) {
  try {
    const endpoint = type === 'budget' ? 'budget-categories' : 'spent-categories'
    const action = item.is_active ? 'deactivate' : 'activate'
    await api(`${endpoint}/${item.id}/${action}/`, 'POST')
    await loadAll()
  } catch (e) {
    alert('Failed to update status.')
  }
}

function formatDate(isoStr) {
  if (!isoStr) return 'Just now'
  return new Date(isoStr).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })
}

onMounted(loadAll)
</script>

<template>
  <div class="categories-page">
    <!-- Page Header -->
    <div class="page-header between-header">
      <div>
        <h1 class="page-title">Category Management</h1>
        <p class="page-subtitle">
          Structure: <span class="tag-cyan">Budget Grouping</span> (Priority 1-10) &rarr;
          <span class="tag-orange">Budget Category</span> (Needs, Wants, Savings) &rarr;
          <span class="tag-green">Spent Category</span> (Supermarket, Meat, Milk)
        </p>
      </div>

      <button class="btn-orange-pill" @click="openCreateDialog">
        + Add {{ currentTab === 'grouping' ? 'Budget Grouping' : (currentTab === 'budget' ? 'Budget Category' : 'Spent Category') }}
      </button>
    </div>

    <!-- Three Links Navigation under Category Section -->
    <div class="category-tabs-bar">
      <button
        class="cat-tab-link"
        :class="{ active: currentTab === 'grouping' }"
        @click="currentTab = 'grouping'"
      >
        <span class="tab-badge">1</span>
        Budget Grouping Category
        <span class="tab-count">({{ groupCategories.length }})</span>
      </button>

      <button
        class="cat-tab-link"
        :class="{ active: currentTab === 'budget' }"
        @click="currentTab = 'budget'"
      >
        <span class="tab-badge">2</span>
        Budget Category
        <span class="tab-count">({{ budgetCategories.length }})</span>
      </button>

      <button
        class="cat-tab-link"
        :class="{ active: currentTab === 'spent' }"
        @click="currentTab = 'spent'"
      >
        <span class="tab-badge">3</span>
        Spent Category
        <span class="tab-count">({{ spentCategories.length }})</span>
      </button>
    </div>

    <!-- Search Input -->
    <div class="search-pill-container" style="margin-top: 1rem;">
      <input
        v-model="searchQuery"
        type="text"
        class="search-pill-input"
        :placeholder="currentTab === 'grouping' ? 'Search Budget Grouping categories (e.g. UPKEEP, HOUSING)...' :
                     currentTab === 'budget' ? 'Search Budget categories (e.g. Shopping, Utilities)...' :
                     'Search Spent categories (e.g. MEAT, milk, supermarket)...'"
      />
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="empty-state">
      <p>Loading categories...</p>
    </div>

    <!-- ==================== TIER 1: BUDGET GROUPING CATEGORY ==================== -->
    <div v-else-if="currentTab === 'grouping'">
      <div v-if="!filteredGroups.length" class="empty-state">
        <h3>No Budget Grouping categories found</h3>
        <p class="muted">Budget Groupings (e.g. UPKEEP, HOUSING) have a priority 1 to 10 used for budget section display ordering.</p>
        <button class="btn-orange-pill" style="margin-top: 1rem;" @click="openCreateDialog">
          + Create First Grouping
        </button>
      </div>

      <div v-else class="data-list-container">
        <div class="data-list-header group-cols">
          <div>Grouping Name</div>
          <div>Display Priority (1 - 10)</div>
          <div>Linked Budget Categories</div>
          <div style="text-align: right;">Actions</div>
        </div>

        <div
          v-for="grp in filteredGroups"
          :key="grp.id"
          class="data-row group-cols"
        >
          <div>
            <h4 class="row-title">{{ grp.name }}</h4>
            <div class="row-subtitle">ID: GRP-{{ grp.id }}</div>
          </div>

          <div>
            <span class="priority-pill" :class="'priority-' + grp.priority">
              Priority: {{ grp.priority }}
            </span>
          </div>

          <div style="color: var(--text-secondary); font-size: 0.9rem;">
            {{ grp.budget_categories_count || 0 }} categories linked
          </div>

          <div class="row-actions">
            <button class="btn-orange-pill" style="padding: 0.35rem 0.95rem; font-size: 0.82rem;" @click="openEditDialog(grp)">
              Edit
            </button>
            <button class="btn-danger-pill" @click="deleteItem(grp.id)">
              Delete
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== TIER 2: BUDGET CATEGORY ==================== -->
    <div v-else-if="currentTab === 'budget'">
      <div v-if="!filteredBudgetCats.length" class="empty-state">
        <h3>No Budget categories found</h3>
        <p class="muted">Budget categories are linked 1-many to a Budget Grouping Category and have a Type (Needs, Wants, Savings).</p>
        <button class="btn-orange-pill" style="margin-top: 1rem;" @click="openCreateDialog">
          + Create Budget Category
        </button>
      </div>

      <div v-else class="data-list-container">
        <div class="data-list-header bcat-cols">
          <div>Budget Category</div>
          <div>Linked Grouping</div>
          <div>Type</div>
          <div>Status</div>
          <div style="text-align: right;">Actions</div>
        </div>

        <div
          v-for="bcat in filteredBudgetCats"
          :key="bcat.id"
          class="data-row bcat-cols"
          :class="{ 'is-inactive': !bcat.is_active }"
        >
          <div>
            <h4 class="row-title">{{ bcat.name }}</h4>
            <div class="row-subtitle">BCAT-{{ bcat.id }}</div>
          </div>

          <div>
            <span style="font-size: 0.9rem; color: var(--text-primary); font-weight: 500;">
              {{ bcat.grouping_name }}
            </span>
            <span class="row-subtitle" style="display: block; font-size: 0.75rem;">
              (Priority: {{ bcat.grouping_priority }})
            </span>
          </div>

          <div>
            <span
              class="badge"
              :class="bcat.category_type === 'needs' ? 'badge-type-budget' :
                     bcat.category_type === 'savings' ? 'badge-savings' : 'badge-type-main'"
            >
              {{ bcat.type_display || bcat.category_type }}
            </span>
          </div>

          <div>
            <span class="badge" :class="bcat.is_active ? 'badge-active' : 'badge-inactive'">
              {{ bcat.is_active ? 'Active' : 'Inactive' }}
            </span>
          </div>

          <div class="row-actions">
            <button class="btn-orange-pill" style="padding: 0.35rem 0.95rem; font-size: 0.82rem;" @click="openEditDialog(bcat)">
              Edit
            </button>
            <button
              class="btn-secondary-pill"
              :class="{ 'btn-danger-pill': bcat.is_active }"
              style="padding: 0.35rem 0.85rem; font-size: 0.8rem;"
              @click="toggleActive(bcat, 'budget')"
            >
              {{ bcat.is_active ? 'Deactivate' : 'Activate' }}
            </button>
            <button class="btn-danger-pill" @click="deleteItem(bcat.id)">
              Delete
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== TIER 3: SPENT CATEGORY ==================== -->
    <div v-else-if="currentTab === 'spent'">
      <div v-if="!filteredSpentCats.length" class="empty-state">
        <h3>No Spent categories found</h3>
        <p class="muted">Spent categories (e.g. supermarket, MEAT, milk) are linked to a Budget Category, and have As Savings and Active flags.</p>
        <button class="btn-orange-pill" style="margin-top: 1rem;" @click="openCreateDialog">
          + Create Spent Category
        </button>
      </div>

      <div v-else class="data-list-container">
        <div class="data-list-header scat-cols">
          <div>Spent Category / Path</div>
          <div>Linked Budget Category</div>
          <div>As Savings</div>
          <div>Status</div>
          <div style="text-align: right;">Actions</div>
        </div>

        <div
          v-for="scat in filteredSpentCats"
          :key="scat.id"
          class="data-row scat-cols"
          :class="{ 'is-inactive': !scat.is_active }"
        >
          <div>
            <h4 class="row-title">{{ scat.name }}</h4>
            <div class="row-subtitle">
              <span class="accent-green">SCAT-{{ scat.id }}</span>
              <span v-if="scat.full_path"> &bull; {{ scat.full_path }}</span>
            </div>
          </div>

          <div>
            <span style="font-size: 0.9rem; color: var(--text-primary); font-weight: 500;">
              {{ scat.budget_category_name || 'No default' }}
            </span>
          </div>

          <div>
            <span class="badge" :class="scat.is_savings ? 'badge-savings' : 'badge-inactive'">
              {{ scat.is_savings ? 'Savings' : 'Standard' }}
            </span>
          </div>

          <div>
            <span class="badge" :class="scat.is_active ? 'badge-active' : 'badge-inactive'">
              {{ scat.is_active ? 'Active' : 'Inactive' }}
            </span>
          </div>

          <div class="row-actions">
            <button class="btn-orange-pill" style="padding: 0.35rem 0.95rem; font-size: 0.82rem;" @click="openEditDialog(scat)">
              Edit
            </button>
            <button
              class="btn-secondary-pill"
              :class="{ 'btn-danger-pill': scat.is_active }"
              style="padding: 0.35rem 0.85rem; font-size: 0.8rem;"
              @click="toggleActive(scat, 'spent')"
            >
              {{ scat.is_active ? 'Deactivate' : 'Activate' }}
            </button>
            <button class="btn-danger-pill" @click="deleteItem(scat.id)">
              Delete
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ==================== MODAL DIALOGS ==================== -->
    <div v-if="showDialog" class="modal-overlay" @click.self="closeDialog">
      <div class="modal-dialog">
        <div class="modal-header">
          <h2 class="modal-title">
            {{ isEditing ? 'Edit ' : 'Create ' }}
            {{ currentTab === 'grouping' ? 'Budget Grouping Category' : (currentTab === 'budget' ? 'Budget Category' : 'Spent Category') }}
          </h2>
          <button class="modal-close-btn" @click="closeDialog">&times;</button>
        </div>

        <form @submit.prevent="saveItem">
          <!-- DIALOG FOR BUDGET GROUPING -->
          <template v-if="currentTab === 'grouping'">
            <div class="form-group">
              <label class="form-label">Grouping Category Name *</label>
              <input
                v-model="groupForm.name"
                class="form-input"
                placeholder="e.g. UPKEEP, HOUSING, TRANSPORT, LEISURE"
                required
                autofocus
              />
            </div>

            <div class="form-group">
              <label class="form-label">Display Priority (1 to 10) *</label>
              <select v-model="groupForm.priority" class="form-select" required>
                <option :value="1">1 (Highest Priority - Appears First)</option>
                <option :value="2">2 - High Priority</option>
                <option :value="3">3 - Standard Priority</option>
                <option :value="4">4 - Priority 4</option>
                <option :value="5">5 - Medium Priority</option>
                <option :value="6">6 - Priority 6</option>
                <option :value="7">7 - Priority 7</option>
                <option :value="8">8 - Priority 8</option>
                <option :value="9">9 - Low Priority</option>
                <option :value="10">10 (Lowest Priority - Appears Last)</option>
              </select>
              <span class="form-hint">Used for budget display section ordering. Lower numbers appear first.</span>
            </div>
          </template>

          <!-- DIALOG FOR BUDGET CATEGORY -->
          <template v-else-if="currentTab === 'budget'">
            <div class="form-group">
              <label class="form-label">Budget Category Name *</label>
              <input
                v-model="budgetForm.name"
                class="form-input"
                placeholder="e.g. Shopping, Utilities, Medical, Education"
                required
                autofocus
              />
            </div>

            <div class="form-group">
              <label class="form-label">Linked Budget Grouping Category *</label>
              <select v-model="budgetForm.grouping" class="form-select" required>
                <option value="" disabled>Select Grouping Category</option>
                <option v-for="g in groupCategories" :key="g.id" :value="g.id">
                  {{ g.name }} (Priority: {{ g.priority }})
                </option>
              </select>
              <span class="form-hint">One-to-many relationship: Grouping contains multiple Budget Categories.</span>
            </div>

            <div class="form-group">
              <label class="form-label">Type *</label>
              <select v-model="budgetForm.category_type" class="form-select" required>
                <option value="needs">Needs (Essential living expenses)</option>
                <option value="wants">Wants (Discretionary & leisure)</option>
                <option value="savings">Savings (Savings goals & emergency fund)</option>
              </select>
            </div>

            <div class="form-group">
              <label class="form-checkbox-row">
                <input v-model="budgetForm.is_active" type="checkbox" />
                <span><strong>Active</strong> (available for budget allocation)</span>
              </label>
            </div>
          </template>

          <!-- DIALOG FOR SPENT CATEGORY -->
          <template v-else>
            <div class="form-group">
              <label class="form-label">Date Created</label>
              <input
                type="text"
                class="form-input"
                :value="isEditing ? formatDate(spentForm.created_at) : 'Automatically set on creation'"
                disabled
                style="opacity: 0.7; cursor: not-allowed;"
              />
            </div>

            <div class="form-group">
              <label class="form-label">Spent Category Name *</label>
              <input
                v-model="spentForm.name"
                class="form-input"
                placeholder="e.g. supermarket, MEAT, milk, fuel, electricity"
                required
                autofocus
              />
            </div>

            <div class="form-group">
              <label class="form-label">Linked Budget Category (Default)</label>
              <select v-model="spentForm.budget_category" class="form-select">
                <option value="">No linked budget category (Unassigned)</option>
                <option v-for="b in budgetCategories" :key="b.id" :value="b.id">
                  {{ b.name }} ({{ b.grouping_name }})
                </option>
              </select>
              <span class="form-hint">Rolls spending up to this budget category.</span>
            </div>

            <div class="form-group">
              <label class="form-checkbox-row">
                <input v-model="spentForm.is_savings" type="checkbox" />
                <span><strong>As Savings</strong> (mark category as savings tracking)</span>
              </label>
            </div>

            <div class="form-group">
              <label class="form-checkbox-row">
                <input v-model="spentForm.is_active" type="checkbox" />
                <span><strong>Active</strong> (available for recording transactions)</span>
              </label>
            </div>
          </template>

          <!-- Error Alert -->
          <p v-if="formError" class="form-error-msg" style="color: var(--text-danger); font-size: 0.88rem; margin: 0.5rem 0;">
            {{ formError }}
          </p>

          <!-- Modal Footer -->
          <div class="modal-footer">
            <button type="button" class="btn-secondary-pill" @click="closeDialog">
              Cancel
            </button>
            <button type="submit" class="btn-orange-pill" :disabled="saving">
              {{ saving ? 'Saving...' : (isEditing ? 'Save Changes' : 'Create') }}
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

/* Three Links Sub-navigation Bar */
.category-tabs-bar {
  display: flex;
  gap: 0.75rem;
  background: var(--bg-card);
  padding: 0.4rem;
  border: 1px solid var(--border-card);
  border-radius: var(--radius-pill);
  width: fit-content;
  max-width: 100%;
  overflow-x: auto;
  margin-bottom: 1.25rem;
}

.cat-tab-link {
  background: transparent;
  border: none;
  border-radius: var(--radius-pill);
  padding: 0.55rem 1.25rem;
  font-size: 0.9rem;
  font-weight: 500;
  color: var(--text-secondary);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  transition: all 0.18s;
  white-space: nowrap;
}

.cat-tab-link:hover:not(.active) {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.04);
}

.cat-tab-link.active {
  background: var(--accent-orange);
  color: #fff;
  font-weight: 600;
  box-shadow: 0 3px 10px rgba(255, 107, 0, 0.35);
}

.tab-badge {
  background: rgba(255, 255, 255, 0.18);
  border-radius: 50%;
  width: 18px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.72rem;
  font-weight: 700;
}

.tab-count {
  font-size: 0.78rem;
  opacity: 0.8;
}

/* Grid columns for each tab */
.group-cols {
  grid-template-columns: 2.5fr 1.8fr 1.8fr 1.5fr;
  gap: 1rem;
}

.bcat-cols {
  grid-template-columns: 2fr 1.8fr 1.2fr 1fr 1.8fr;
  gap: 1rem;
}

.scat-cols {
  grid-template-columns: 2.2fr 1.8fr 1.2fr 1fr 1.8fr;
  gap: 1rem;
}

/* Priority Pills */
.priority-pill {
  display: inline-flex;
  align-items: center;
  padding: 0.2rem 0.7rem;
  border-radius: var(--radius-pill);
  font-size: 0.78rem;
  font-weight: 700;
  background: rgba(255, 107, 0, 0.12);
  color: var(--accent-orange);
  border: 1px solid rgba(255, 107, 0, 0.3);
}

.priority-1, .priority-2 {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
  border-color: rgba(239, 68, 68, 0.35);
}

.priority-3, .priority-4, .priority-5 {
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
  border-color: rgba(245, 158, 11, 0.35);
}

.priority-6, .priority-7, .priority-8, .priority-9, .priority-10 {
  background: rgba(56, 189, 248, 0.15);
  color: #38bdf8;
  border-color: rgba(56, 189, 248, 0.35);
}

@media (max-width: 900px) {
  .group-cols, .bcat-cols, .scat-cols {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
