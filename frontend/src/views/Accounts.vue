<script setup>
import { ref, computed, onMounted } from 'vue'
import { api, money, today } from '../api'

// Available Account Kinds
const accountKinds = [
  { id: 'bank', name: 'Bank Account', icon: '🏦' },
  { id: 'mpesa', name: 'M-Pesa Mobile Money', icon: '📱' },
  { id: 'cash', name: 'Cash Wallet', icon: '💵' },
  { id: 'sacco', name: 'SACCO Account', icon: '🤝' },
  { id: 'mmf', name: 'Money Market Fund (MMF)', icon: '📈' },
  { id: 'investment', name: 'Investment / Stocks', icon: '💎' },
  { id: 'credit_card', name: 'Credit Card', icon: '💳' },
]

function getKindMeta(kind) {
  return accountKinds.find(k => k.id === kind) || { id: kind, name: kind, icon: '💰' }
}

const accounts = ref([])
const loading = ref(true)
const err = ref('')
const showArchived = ref(false)

// Modals State
const showAccountModal = ref(false)
const isEditing = ref(false)
const modalError = ref('')
const saving = ref(false)

const showTransferModal = ref(false)
const transferError = ref('')
const transferSaving = ref(false)

const showReconcileModal = ref(false)
const reconcileAccount = ref(null)
const reconcileActual = ref('')
const reconcileDate = ref(today)
const reconcileNotes = ref('')
const reconcileError = ref('')
const reconcileSuccess = ref('')
const reconcileSaving = ref(false)

const showInsightsModal = ref(false)
const insightsAccount = ref(null)
const insightsData = ref(null)
const insightsLoading = ref(false)
const insightsTimeframe = ref('month')

// Form definitions
const defaultAccountForm = () => ({
  id: null,
  name: '',
  kind: 'bank',
  account_number: '',
  opening_balance: '',
  as_of_date: today,
  minimum_balance: '',
  parent: null,
  is_pot: false,
  is_default: false
})
const accountForm = ref(defaultAccountForm())

const defaultTransferForm = () => ({
  from_account: '',
  to_account: '',
  amount: '',
  fee: '',
  transaction_date: today,
  narrative: ''
})
const transferForm = ref(defaultTransferForm())

// Load all accounts including archived
async function loadAccounts() {
  loading.value = true
  err.value = ''
  try {
    const data = await api('accounts/?include_archived=true')
    accounts.value = data
  } catch (e) {
    err.value = 'Failed to load accounts. ' + (e?.error || '')
  } finally {
    loading.value = false
  }
}

// Filtered and Grouped Accounts
const activeAccounts = computed(() => accounts.value.filter(a => !a.is_archived))
const archivedAccounts = computed(() => accounts.value.filter(a => a.is_archived))

// Top-level parent accounts (parent is null)
const topLevelActiveAccounts = computed(() => {
  return activeAccounts.value.filter(a => !a.parent)
})

// Sub-accounts / pots grouped by parent id
function getSubAccounts(parentId) {
  return activeAccounts.value.filter(a => a.parent === parentId)
}

// KPI totals
const totalNetWorth = computed(() => {
  return activeAccounts.value.reduce((acc, a) => acc + (Number(a.balance) || 0), 0)
})

const totalLiquid = computed(() => {
  return activeAccounts.value.filter(a => !a.is_pot).reduce((acc, a) => acc + (Number(a.balance) || 0), 0)
})

const totalPots = computed(() => {
  return activeAccounts.value.filter(a => a.is_pot).reduce((acc, a) => acc + (Number(a.balance) || 0), 0)
})

const lowBalanceCount = computed(() => {
  return activeAccounts.value.filter(a => a.is_low_balance).length
})

// Potential parent accounts for pots dropdown (only active non-pot accounts)
const parentAccountOptions = computed(() => {
  return activeAccounts.value.filter(a => !a.is_pot && (!accountForm.value.id || a.id !== accountForm.value.id))
})

// Account Creation & Editing
function openAddAccountModal(presetParent = null, isPot = false) {
  accountForm.value = defaultAccountForm()
  isEditing.value = false
  modalError.value = ''
  if (presetParent) {
    accountForm.value.parent = presetParent.id
    accountForm.value.kind = presetParent.kind
  }
  if (isPot) {
    accountForm.value.is_pot = true
  }
  showAccountModal.value = true
}

function openEditAccountModal(account) {
  accountForm.value = {
    id: account.id,
    name: account.name,
    kind: account.kind,
    account_number: account.account_number || '',
    opening_balance: account.opening_balance,
    as_of_date: account.as_of_date || today,
    minimum_balance: account.minimum_balance || '',
    parent: account.parent || null,
    is_pot: account.is_pot || false,
    is_default: account.is_default || false
  }
  isEditing.value = true
  modalError.value = ''
  showAccountModal.value = true
}

async function saveAccount() {
  modalError.value = ''
  saving.value = true
  try {
    const payload = {
      name: accountForm.value.name.trim(),
      kind: accountForm.value.kind,
      account_number: accountForm.value.account_number.trim(),
      opening_balance: accountForm.value.opening_balance === '' ? 0 : Number(accountForm.value.opening_balance),
      as_of_date: accountForm.value.as_of_date || today,
      minimum_balance: accountForm.value.minimum_balance === '' ? 0 : Number(accountForm.value.minimum_balance),
      parent: accountForm.value.parent || null,
      is_pot: Boolean(accountForm.value.is_pot),
      is_default: Boolean(accountForm.value.is_default)
    }

    if (isEditing.value) {
      await api(`accounts/${accountForm.value.id}/`, 'PATCH', payload)
    } else {
      await api('accounts/', 'POST', payload)
    }
    showAccountModal.value = false
    await loadAccounts()
  } catch (e) {
    modalError.value = typeof e === 'object' ? Object.values(e).flat().join(' ') : 'Failed to save account.'
  } finally {
    saving.value = false
  }
}

async function deleteAccount(account) {
  if (confirm(`Are you sure you want to delete "${account.name}"? This will delete all historical transactions associated with this account.`)) {
    try {
      await api(`accounts/${account.id}/`, 'DELETE')
      await loadAccounts()
    } catch (e) {
      alert('Failed to delete account. ' + (e?.error || ''))
    }
  }
}

async function setAccountDefault(account) {
  try {
    await api(`accounts/${account.id}/set_default/`, 'POST')
    await loadAccounts()
  } catch (e) {
    alert('Failed to set default account.')
  }
}

async function archiveAccount(account) {
  if (confirm(`Archive account "${account.name}"? It will be hidden from new transaction entries while preserving all past transactions and budget reports.`)) {
    try {
      await api(`accounts/${account.id}/archive/`, 'POST')
      await loadAccounts()
    } catch (e) {
      alert('Failed to archive account.')
    }
  }
}

async function unarchiveAccount(account) {
  try {
    await api(`accounts/${account.id}/unarchive/`, 'POST')
    await loadAccounts()
  } catch (e) {
    alert('Failed to unarchive account.')
  }
}

// Dedicated Transfer Flow
function openTransferModal(fromAccount = null, toAccount = null) {
  transferForm.value = defaultTransferForm()
  transferError.value = ''
  if (fromAccount) {
    transferForm.value.from_account = fromAccount.id
  } else if (activeAccounts.value.length) {
    const def = activeAccounts.value.find(a => a.is_default) || activeAccounts.value[0]
    transferForm.value.from_account = def.id
  }

  if (toAccount) {
    transferForm.value.to_account = toAccount.id
  } else if (activeAccounts.value.length > 1) {
    const candidate = activeAccounts.value.find(a => a.id !== transferForm.value.from_account)
    if (candidate) transferForm.value.to_account = candidate.id
  }
  showTransferModal.value = true
}

const selectedFromAccount = computed(() => {
  return activeAccounts.value.find(a => a.id === transferForm.value.from_account)
})

const selectedToAccount = computed(() => {
  return activeAccounts.value.find(a => a.id === transferForm.value.to_account)
})

const transferTotalDeducted = computed(() => {
  const amt = Number(transferForm.value.amount) || 0
  const fee = Number(transferForm.value.fee) || 0
  return amt + fee
})

const transferRemainingBalance = computed(() => {
  if (!selectedFromAccount.value) return 0
  return Number(selectedFromAccount.value.balance) - transferTotalDeducted.value
})

const transferWillTriggerLowBalance = computed(() => {
  if (!selectedFromAccount.value) return false
  const min = Number(selectedFromAccount.value.minimum_balance) || 0
  if (min <= 0) return false
  return transferRemainingBalance.value < min
})

async function submitTransfer() {
  transferError.value = ''
  transferSaving.value = true
  try {
    const payload = {
      kind: 'transfer',
      account: transferForm.value.from_account,
      to_account: transferForm.value.to_account,
      amount: Number(transferForm.value.amount),
      fee: transferForm.value.fee === '' ? 0 : Number(transferForm.value.fee),
      transaction_date: transferForm.value.transaction_date || today,
      description: transferForm.value.narrative.trim() || 'Account transfer'
    }

    await api('transactions/', 'POST', payload)
    showTransferModal.value = false
    await loadAccounts()
  } catch (e) {
    transferError.value = typeof e === 'object' ? Object.values(e).flat().join(' ') : 'Transfer failed.'
  } finally {
    transferSaving.value = false
  }
}

// Reconciliation Flow
function openReconcileModal(account) {
  reconcileAccount.value = account
  reconcileActual.value = account.balance.toFixed(2)
  reconcileDate.value = today
  reconcileNotes.value = ''
  reconcileError.value = ''
  reconcileSuccess.value = ''
  showReconcileModal.value = true
}

const reconcileDifference = computed(() => {
  if (!reconcileAccount.value || reconcileActual.value === '') return 0
  const actual = Number(reconcileActual.value) || 0
  const current = Number(reconcileAccount.value.balance) || 0
  return Number((actual - current).toFixed(2))
})

async function submitReconciliation() {
  reconcileError.value = ''
  reconcileSuccess.value = ''
  reconcileSaving.value = true
  try {
    const payload = {
      actual_balance: Number(reconcileActual.value),
      date: reconcileDate.value || today,
      notes: reconcileNotes.value.trim()
    }
    const res = await api(`accounts/${reconcileAccount.value.id}/reconcile/`, 'POST', payload)
    reconcileSuccess.value = res.message || 'Reconciliation successful!'
    setTimeout(async () => {
      showReconcileModal.value = false
      await loadAccounts()
    }, 900)
  } catch (e) {
    reconcileError.value = typeof e === 'object' ? Object.values(e).flat().join(' ') : 'Reconciliation failed.'
  } finally {
    reconcileSaving.value = false
  }
}

// Insights Mini-Dashboard Flow
async function openInsightsModal(account) {
  insightsAccount.value = account
  showInsightsModal.value = true
  await fetchInsights()
}

async function fetchInsights() {
  if (!insightsAccount.value) return
  insightsLoading.value = true
  try {
    const data = await api(`accounts/${insightsAccount.value.id}/insights/?timeframe=${insightsTimeframe.value}`)
    insightsData.value = data
  } catch (e) {
    alert('Failed to load insights for this account.')
  } finally {
    insightsLoading.value = false
  }
}

function setInsightsTimeframe(tf) {
  insightsTimeframe.value = tf
  fetchInsights()
}

onMounted(loadAccounts)
</script>

<template>
  <div class="accounts-page-view">
    <!-- Header with Quick Action Buttons -->
    <header class="page-header between">
      <div>
        <h1 class="page-title">Bank & Mobile Money Accounts</h1>
        <p class="page-subtitle">
          Manage your liquid wallets, bank accounts, savings pots, reconciliations, and transfers.
        </p>
      </div>

      <div class="row-actions">
        <button class="btn-orange-pill" @click="openAddAccountModal()">
          <span>➕ Add Account</span>
        </button>
        <button class="btn-secondary-pill" @click="openTransferModal()">
          <span>🔁 Transfer Money</span>
        </button>
        <button
          v-if="archivedAccounts.length"
          class="btn-secondary-pill"
          :class="{ active: showArchived }"
          @click="showArchived = !showArchived"
        >
          <span>{{ showArchived ? 'Hide Archived' : `Show Archived (${archivedAccounts.length})` }}</span>
        </button>
      </div>
    </header>

    <!-- Top Executive Summary Cards -->
    <section class="account-kpi-grid">
      <div class="account-kpi-card kpi-accent">
        <span class="account-kpi-label">💳 Total Net Worth</span>
        <span class="account-kpi-val">{{ money(totalNetWorth) }}</span>
        <span class="muted" style="font-size: 0.76rem;">All active liquid + savings pots</span>
      </div>

      <div class="account-kpi-card kpi-green">
        <span class="account-kpi-label">💧 Liquid Funds</span>
        <span class="account-kpi-val">{{ money(totalLiquid) }}</span>
        <span class="muted" style="font-size: 0.76rem;">Available for immediate spending</span>
      </div>

      <div class="account-kpi-card kpi-cyan">
        <span class="account-kpi-label">🔒 Locked in Pots</span>
        <span class="account-kpi-val">{{ money(totalPots) }}</span>
        <span class="muted" style="font-size: 0.76rem;">M-Shwari & fixed goal savings</span>
      </div>

      <div class="account-kpi-card" :class="lowBalanceCount > 0 ? 'kpi-warn' : ''">
        <span class="account-kpi-label">⚠️ Balance Alerts</span>
        <span class="account-kpi-val">{{ lowBalanceCount }}</span>
        <span class="muted" style="font-size: 0.76rem;">
          {{ lowBalanceCount > 0 ? 'Accounts below minimum threshold' : 'All accounts within safety limits' }}
        </span>
      </div>
    </section>

    <!-- Loading & Error states -->
    <div v-if="loading" class="empty-state">
      <p>Loading your accounts...</p>
    </div>

    <div v-else-if="err" class="alert-box" style="margin-bottom: 1.5rem;">
      <span class="neg">{{ err }}</span>
    </div>

    <div v-else-if="!activeAccounts.length && !archivedAccounts.length" class="empty-state">
      <h3>No accounts found</h3>
      <p class="muted">Add your primary bank account or M-Pesa wallet to get started.</p>
      <button class="btn-orange-pill" style="margin-top: 1rem;" @click="openAddAccountModal()">
        Add your first account
      </button>
    </div>

    <!-- Active Accounts List -->
    <section v-else class="accounts-grid">
      <div
        v-for="account in topLevelActiveAccounts"
        :key="account.id"
        class="account-card"
        :class="{ 'low-balance': account.is_low_balance }"
      >
        <!-- Account Card Header -->
        <div class="account-header-row">
          <div class="account-title-group">
            <div class="account-avatar">
              {{ getKindMeta(account.kind).icon }}
            </div>
            <div class="account-title-text">
              <h3 class="account-name">
                {{ account.name }}
                <span v-if="account.is_default" class="badge badge-default">⭐ Default</span>
                <span class="badge badge-active">{{ getKindMeta(account.kind).name }}</span>
                <span v-if="account.is_low_balance" class="badge badge-low-balance">⚠️ Low Balance</span>
              </h3>
              <div class="account-subtitle">
                <span v-if="account.account_number">Acc/Till: {{ account.account_number }} &bull;</span>
                <span>Opening: {{ money(account.opening_balance) }} (as of {{ account.as_of_date }})</span>
                <span v-if="Number(account.minimum_balance) > 0">&bull; Min Threshold: {{ money(account.minimum_balance) }}</span>
              </div>
            </div>
          </div>

          <!-- Quick Action Buttons -->
          <div class="row-actions">
            <button class="btn-action-pill btn-insights" @click="openInsightsModal(account)">
              📊 Insights
            </button>
            <button class="btn-action-pill btn-reconcile" @click="openReconcileModal(account)">
              ⚖️ Reconcile
            </button>
            <button class="btn-action-pill btn-transfer" @click="openTransferModal(account)">
              🔁 Transfer
            </button>
          </div>
        </div>

        <!-- Low Balance Alert Warning Banner -->
        <div v-if="account.is_low_balance" class="low-balance-alert-banner">
          <span>⚠️ Low Balance Warning: Balance of {{ money(account.balance) }} is below your minimum threshold of {{ money(account.minimum_balance) }}. Top up to avoid failed transactions.</span>
        </div>

        <!-- Account Balance Section -->
        <div class="account-balance-section">
          <div class="balance-box">
            <span class="balance-label">Liquid Balance</span>
            <span class="balance-amount highlight">{{ money(account.liquid_balance) }}</span>
          </div>

          <div v-if="getSubAccounts(account.id).length" class="balance-box">
            <span class="balance-label">Total Balance (With Pots)</span>
            <span class="balance-amount">{{ money(account.total_balance) }}</span>
          </div>

          <div class="balance-aux-info">
            <span v-if="getSubAccounts(account.id).length" class="aux-tag">
              🍯 {{ getSubAccounts(account.id).length }} Sub-Account{{ getSubAccounts(account.id).length > 1 ? 's' : '' }} / Pots
            </span>
            <button
              v-if="!account.is_default"
              class="btn-secondary-pill"
              style="font-size: 0.78rem; padding: 0.25rem 0.65rem;"
              @click="setAccountDefault(account)"
            >
              Set as Default
            </button>
          </div>
        </div>

        <!-- Sub-accounts / Pots Nested Block -->
        <div v-if="getSubAccounts(account.id).length || !account.is_pot" class="pots-container">
          <div class="pots-header">
            <span>Locked Goals & Savings Pots</span>
            <button
              class="link"
              style="font-size: 0.78rem;"
              @click="openAddAccountModal(account, true)"
            >
              ➕ Add Pot
            </button>
          </div>

          <div v-if="!getSubAccounts(account.id).length" class="muted" style="font-size: 0.8rem; padding: 0.35rem 0;">
            No pots under this account. Create one for M-Shwari Lock Savings or goal buckets.
          </div>

          <div
            v-for="pot in getSubAccounts(account.id)"
            :key="pot.id"
            class="pot-row"
          >
            <div class="pot-meta">
              <span class="pot-icon">🍯</span>
              <div>
                <span class="pot-name">{{ pot.name }}</span>
                <small class="muted"> &bull; {{ getKindMeta(pot.kind).name }}</small>
                <div v-if="Number(pot.minimum_balance) > 0" class="muted" style="font-size: 0.75rem;">
                  Min: {{ money(pot.minimum_balance) }}
                </div>
              </div>
            </div>

            <div class="between" style="gap: 1rem;">
              <span class="pot-balance">{{ money(pot.balance) }}</span>
              <div class="row-actions">
                <button
                  class="btn-action-pill"
                  title="Transfer from parent account to this pot"
                  @click="openTransferModal(account, pot)"
                >
                  Deposit
                </button>
                <button
                  class="btn-action-pill"
                  title="Withdraw from this pot back to parent account"
                  @click="openTransferModal(pot, account)"
                >
                  Withdraw
                </button>
                <button class="btn-action-pill btn-reconcile" @click="openReconcileModal(pot)">
                  ⚖️
                </button>
                <button class="btn-action-pill" @click="openEditAccountModal(pot)">
                  ✏️
                </button>
                <button class="link" style="color: var(--text-danger);" @click="deleteAccount(pot)">
                  Delete
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Bottom Controls Bar -->
        <div class="account-actions-bar">
          <button class="btn-action-pill" @click="openEditAccountModal(account)">
            ✏️ Edit Account
          </button>
          <button class="btn-action-pill" @click="archiveAccount(account)">
            🗄️ Archive / Hide
          </button>
          <button class="link" style="color: var(--text-danger);" @click="deleteAccount(account)">
            Delete
          </button>
        </div>
      </div>

      <!-- Standalone Sub-accounts (pots whose parent is archived or not set) -->
      <div
        v-for="account in activeAccounts.filter(a => a.is_pot && a.parent && !topLevelActiveAccounts.some(p => p.id === a.parent))"
        :key="account.id"
        class="account-card"
      >
        <div class="account-header-row">
          <div class="account-title-group">
            <div class="account-avatar">🍯</div>
            <div class="account-title-text">
              <h3 class="account-name">
                {{ account.name }}
                <span class="badge badge-pot">Savings Pot</span>
              </h3>
              <div class="account-subtitle">
                <span>Balance: {{ money(account.balance) }}</span>
              </div>
            </div>
          </div>
          <div class="row-actions">
            <button class="btn-action-pill btn-reconcile" @click="openReconcileModal(account)">
              ⚖️ Reconcile
            </button>
            <button class="btn-action-pill" @click="openEditAccountModal(account)">
              ✏️ Edit
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- Archived Accounts Section (Collapsible) -->
    <section v-if="showArchived && archivedAccounts.length" style="margin-top: 2.5rem;">
      <h2 style="color: var(--text-muted); font-size: 1.1rem; margin-bottom: 1rem;">
        🗄️ Archived Accounts (Hidden from Daily Spends)
      </h2>
      <div class="accounts-grid">
        <div
          v-for="account in archivedAccounts"
          :key="account.id"
          class="account-card is-archived"
        >
          <div class="account-header-row">
            <div class="account-title-group">
              <div class="account-avatar">{{ getKindMeta(account.kind).icon }}</div>
              <div class="account-title-text">
                <h3 class="account-name">
                  {{ account.name }}
                  <span class="badge badge-inactive">Archived</span>
                </h3>
                <div class="account-subtitle">
                  Past historical transactions are preserved for budget reports.
                </div>
              </div>
            </div>

            <div class="between" style="gap: 1rem;">
              <span class="balance-amount">{{ money(account.balance) }}</span>
              <div class="row-actions">
                <button class="btn-orange-pill" style="font-size: 0.8rem; padding: 0.35rem 0.9rem;" @click="unarchiveAccount(account)">
                  Unarchive / Restore
                </button>
                <button class="btn-action-pill btn-insights" @click="openInsightsModal(account)">
                  📊 History
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 1. ADD / EDIT ACCOUNT MODAL -->
    <div v-if="showAccountModal" class="modal-overlay" @click.self="showAccountModal = false">
      <div class="modal-dialog">
        <div class="modal-header">
          <h3 class="modal-title">{{ isEditing ? 'Edit Account' : 'Add New Account' }}</h3>
          <button class="modal-close-btn" @click="showAccountModal = false">&times;</button>
        </div>

        <form @submit.prevent="saveAccount">
          <p v-if="modalError" class="neg" style="margin-bottom: 0.75rem;">{{ modalError }}</p>

          <div class="form-group">
            <label class="form-label">Account Name *</label>
            <input
              v-model="accountForm.name"
              class="form-input"
              placeholder="e.g. M-Pesa, KCB Checking, Cash Float"
              required
            />
          </div>

          <div class="form-group">
            <label class="form-label">Account Type *</label>
            <select v-model="accountForm.kind" class="form-select">
              <option v-for="k in accountKinds" :key="k.id" :value="k.id">
                {{ k.icon }} {{ k.name }}
              </option>
            </select>
          </div>

          <div class="form-group">
            <label class="form-label">Account Number / Till / Paybill (Optional)</label>
            <input
              v-model="accountForm.account_number"
              class="form-input"
              placeholder="e.g. 1234567890 or Till 882910"
            />
          </div>

          <div class="row" style="margin: 0 0 1rem 0;">
            <div class="form-group" style="flex: 1; margin: 0;">
              <label class="form-label">Opening Starting Balance</label>
              <input
                v-model="accountForm.opening_balance"
                type="number"
                step="0.01"
                class="form-input"
                placeholder="0.00"
              />
              <span class="form-hint">Does not distort monthly income analytics.</span>
            </div>

            <div class="form-group" style="flex: 1; margin: 0;">
              <label class="form-label">As-Of Date</label>
              <input
                v-model="accountForm.as_of_date"
                type="date"
                class="form-input"
              />
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">Minimum Balance Alert Threshold (KES)</label>
            <input
              v-model="accountForm.minimum_balance"
              type="number"
              step="0.01"
              min="0"
              class="form-input"
              placeholder="e.g. 1000.00 (Leave 0 for no alert)"
            />
            <span class="form-hint">Get alerted if your balance drops below this threshold.</span>
          </div>

          <!-- Sub-account / Pot grouping option -->
          <div class="form-group">
            <label class="form-label">Parent Account (For Sub-Accounts / Pots)</label>
            <select v-model="accountForm.parent" class="form-select">
              <option :value="null">-- Standalone Account (No Parent) --</option>
              <option v-for="p in parentAccountOptions" :key="p.id" :value="p.id">
                {{ getKindMeta(p.kind).icon }} {{ p.name }} (Parent)
              </option>
            </select>
            <span class="form-hint">Nest locked goals (like M-Shwari Lock) under a main wallet.</span>
          </div>

          <label class="form-checkbox-row">
            <input v-model="accountForm.is_pot" type="checkbox" />
            <span>This is a savings pot / locked goal</span>
          </label>

          <label class="form-checkbox-row">
            <input v-model="accountForm.is_default" type="checkbox" />
            <span>Set as primary default account (pre-selected in new spends)</span>
          </label>

          <div class="modal-footer">
            <button type="button" class="btn-secondary-pill" @click="showAccountModal = false">Cancel</button>
            <button type="submit" class="btn-orange-pill" :disabled="saving">
              {{ saving ? 'Saving...' : (isEditing ? 'Save Changes' : 'Create Account') }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- 2. DEDICATED ACCOUNT-TO-ACCOUNT TRANSFER MODAL -->
    <div v-if="showTransferModal" class="modal-overlay" @click.self="showTransferModal = false">
      <div class="modal-dialog">
        <div class="modal-header">
          <h3 class="modal-title">🔁 Transfer Money</h3>
          <button class="modal-close-btn" @click="showTransferModal = false">&times;</button>
        </div>

        <form @submit.prevent="submitTransfer">
          <p v-if="transferError" class="neg" style="margin-bottom: 0.75rem;">{{ transferError }}</p>

          <div class="row" style="margin: 0 0 1rem 0;">
            <div class="form-group" style="flex: 1; margin: 0;">
              <label class="form-label">From Account (Source) *</label>
              <select v-model="transferForm.from_account" class="form-select" required>
                <option value="" disabled>Select source account</option>
                <option v-for="a in activeAccounts" :key="a.id" :value="a.id">
                  {{ a.name }} ({{ money(a.balance) }})
                </option>
              </select>
            </div>

            <div class="form-group" style="flex: 1; margin: 0;">
              <label class="form-label">To Account (Destination) *</label>
              <select v-model="transferForm.to_account" class="form-select" required>
                <option value="" disabled>Select destination account</option>
                <option v-for="a in activeAccounts" :key="a.id" :value="a.id" :disabled="a.id === transferForm.from_account">
                  {{ a.name }} ({{ money(a.balance) }})
                </option>
              </select>
            </div>
          </div>

          <div class="row" style="margin: 0 0 1rem 0;">
            <div class="form-group" style="flex: 1; margin: 0;">
              <label class="form-label">Transfer Amount (KES) *</label>
              <input
                v-model="transferForm.amount"
                type="number"
                step="0.01"
                min="0.01"
                class="form-input"
                placeholder="0.00"
                required
              />
            </div>

            <div class="form-group" style="flex: 1; margin: 0;">
              <label class="form-label">Transaction Fee / Tariff (KES)</label>
              <input
                v-model="transferForm.fee"
                type="number"
                step="0.01"
                min="0"
                class="form-input"
                placeholder="e.g. 13.00 or 25.00"
              />
              <span class="form-hint">M-Pesa or bank transfer charge</span>
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">Date</label>
            <input v-model="transferForm.transaction_date" type="date" class="form-input" />
          </div>

          <div class="form-group">
            <label class="form-label">Description / Reference Note</label>
            <input
              v-model="transferForm.narrative"
              class="form-input"
              placeholder="e.g. Float top-up, M-Pesa to Bank, Lock savings transfer"
            />
          </div>

          <!-- Real-Time Calculation Preview -->
          <div v-if="selectedFromAccount && selectedToAccount && transferForm.amount" class="transfer-preview-box">
            <div>
              Deducted from <strong>{{ selectedFromAccount.name }}</strong>:
              <span class="neg"><strong>{{ money(transferTotalDeducted) }}</strong></span>
              <span class="muted"> ({{ money(transferForm.amount) }} transfer + {{ money(transferForm.fee || 0) }} tariff)</span>
            </div>
            <div>
              Credited to <strong>{{ selectedToAccount.name }}</strong>:
              <span class="tag-green"><strong>{{ money(transferForm.amount) }}</strong></span>
            </div>
            <div v-if="transferWillTriggerLowBalance" class="neg" style="margin-top: 0.35rem; font-weight: 600;">
              ⚠️ Warning: This transfer will reduce {{ selectedFromAccount.name }} to {{ money(transferRemainingBalance) }}, which is below its minimum threshold of {{ money(selectedFromAccount.minimum_balance) }}.
            </div>
          </div>

          <div class="modal-footer">
            <button type="button" class="btn-secondary-pill" @click="showTransferModal = false">Cancel</button>
            <button type="submit" class="btn-orange-pill" :disabled="transferSaving || !transferForm.amount">
              {{ transferSaving ? 'Processing Transfer...' : 'Complete Transfer' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- 3. BALANCE RECONCILIATION MODAL -->
    <div v-if="showReconcileModal && reconcileAccount" class="modal-overlay" @click.self="showReconcileModal = false">
      <div class="modal-dialog">
        <div class="modal-header">
          <h3 class="modal-title">⚖️ Reconcile Balance: {{ reconcileAccount.name }}</h3>
          <button class="modal-close-btn" @click="showReconcileModal = false">&times;</button>
        </div>

        <form @submit.prevent="submitReconciliation">
          <p v-if="reconcileError" class="neg" style="margin-bottom: 0.75rem;">{{ reconcileError }}</p>
          <p v-if="reconcileSuccess" class="tag-green" style="margin-bottom: 0.75rem; font-weight: 600;">
            {{ reconcileSuccess }}
          </p>

          <p class="muted" style="font-size: 0.88rem; margin: 0 0 1rem 0;">
            Enter the exact actual balance shown in your M-Pesa SMS or banking app. The app generates a silent "Balance Adjustment" transaction for any forgotten pennies or untracked tariffs.
          </p>

          <div class="form-group">
            <label class="form-label">Current App Balance</label>
            <input
              :value="money(reconcileAccount.balance)"
              class="form-input"
              disabled
              style="opacity: 0.8; font-weight: 600;"
            />
          </div>

          <div class="form-group">
            <label class="form-label">Actual Balance (From Bank App or M-Pesa SMS) *</label>
            <input
              v-model="reconcileActual"
              type="number"
              step="0.01"
              class="form-input"
              placeholder="e.g. 5420.50"
              required
              autofocus
            />
          </div>

          <!-- Difference indicator -->
          <div class="transfer-preview-box">
            <div class="between">
              <span>Adjustment Difference:</span>
              <strong :class="reconcileDifference < 0 ? 'neg' : (reconcileDifference > 0 ? 'tag-green' : '')">
                {{ reconcileDifference > 0 ? '+' : '' }}{{ money(reconcileDifference) }}
              </strong>
            </div>
            <div style="font-size: 0.8rem; margin-top: 0.2rem;">
              <span v-if="reconcileDifference < 0">
                📉 Deficit: A silent debit of {{ money(Math.abs(reconcileDifference)) }} will be recorded to match your actual balance.
              </span>
              <span v-else-if="reconcileDifference > 0">
                📈 Surplus: A silent credit of {{ money(reconcileDifference) }} will be recorded to match your actual balance.
              </span>
              <span v-else class="tag-green">
                ✅ Balances match perfectly! No adjustment transaction will be recorded.
              </span>
            </div>
          </div>

          <div class="form-group" style="margin-top: 1rem;">
            <label class="form-label">As-Of Date</label>
            <input v-model="reconcileDate" type="date" class="form-input" />
          </div>

          <div class="form-group">
            <label class="form-label">Reconciliation Note (Optional)</label>
            <input
              v-model="reconcileNotes"
              class="form-input"
              placeholder="e.g. Reconciled with KCB mobile banking SMS"
            />
          </div>

          <div class="modal-footer">
            <button type="button" class="btn-secondary-pill" @click="showReconcileModal = false">Cancel</button>
            <button type="submit" class="btn-orange-pill" :disabled="reconcileSaving">
              {{ reconcileSaving ? 'Reconciling...' : 'Confirm & Apply Adjustment' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- 4. ACCOUNT INSIGHTS MINI-DASHBOARD MODAL -->
    <div v-if="showInsightsModal && insightsAccount" class="modal-overlay" @click.self="showInsightsModal = false">
      <div class="modal-dialog" style="max-width: 680px; max-height: 90vh; overflow-y: auto;">
        <div class="modal-header">
          <div>
            <h3 class="modal-title">📊 {{ insightsAccount.name }} Insights</h3>
            <span class="muted" style="font-size: 0.82rem;">
              {{ getKindMeta(insightsAccount.kind).name }} &bull; Current Balance: {{ money(insightsAccount.balance) }}
            </span>
          </div>
          <button class="modal-close-btn" @click="showInsightsModal = false">&times;</button>
        </div>

        <div v-if="insightsLoading" class="empty-state">
          <p>Analyzing wallet activity...</p>
        </div>

        <div v-else-if="insightsData" class="insights-modal-body">
          <!-- Timeframe selector -->
          <div class="between" style="border-bottom: 1px solid var(--divider-subtle); padding-bottom: 0.85rem;">
            <span style="font-weight: 600; font-size: 0.88rem;">Analysis Timeframe:</span>
            <div class="row-actions">
              <button
                class="filter-btn"
                :class="{ active: insightsTimeframe === 'month' }"
                @click="setInsightsTimeframe('month')"
              >
                This Month
              </button>
              <button
                class="filter-btn"
                :class="{ active: insightsTimeframe === 'all' }"
                @click="setInsightsTimeframe('all')"
              >
                All Time
              </button>
            </div>
          </div>

          <!-- Metric KPI Grid -->
          <div class="insights-kpi-grid">
            <div class="insight-kpi-box insight-inflow">
              <span class="label">🟢 Total Inflow</span>
              <span class="amount">{{ money(insightsData.inflow.total) }}</span>
              <span class="muted" style="font-size: 0.72rem;">
                Income: {{ money(insightsData.inflow.income) }} | Transfers In: {{ money(insightsData.inflow.transfers_in) }}
              </span>
            </div>

            <div class="insight-kpi-box insight-outflow">
              <span class="label">🔴 Total Outflow</span>
              <span class="amount">{{ money(insightsData.outflow.total) }}</span>
              <span class="muted" style="font-size: 0.72rem;">
                Expenses: {{ money(insightsData.outflow.expenses) }} | Fees: {{ money(insightsData.outflow.fees) }}
              </span>
            </div>

            <div class="insight-kpi-box insight-net">
              <span class="label">⚖️ Net Cash Flow</span>
              <span class="amount" :class="insightsData.net_flow >= 0 ? 'tag-green' : 'neg'">
                {{ insightsData.net_flow >= 0 ? '+' : '' }}{{ money(insightsData.net_flow) }}
              </span>
              <span class="muted" style="font-size: 0.72rem;">Inflow minus Outflow</span>
            </div>

            <div class="insight-kpi-box insight-daily">
              <span class="label">⏱️ Avg. Daily Spend</span>
              <span class="amount">{{ money(insightsData.average_daily_spend) }}</span>
              <span class="muted" style="font-size: 0.72rem;">Average outflow per active day</span>
            </div>
          </div>

          <!-- Cash Inflow vs Outflow Visual Bar -->
          <div class="flow-ratio-bar-wrapper">
            <div class="between" style="font-size: 0.82rem;">
              <span class="tag-green">Inflow ({{ money(insightsData.inflow.total) }})</span>
              <span class="neg">Outflow ({{ money(insightsData.outflow.total) }})</span>
            </div>
            <div class="flow-bar">
              <div
                class="flow-bar-segment-in"
                :style="{
                  width: `${(insightsData.inflow.total / ((insightsData.inflow.total + insightsData.outflow.total) || 1)) * 100}%`
                }"
              ></div>
              <div
                class="flow-bar-segment-out"
                :style="{
                  width: `${(insightsData.outflow.total / ((insightsData.inflow.total + insightsData.outflow.total) || 1)) * 100}%`
                }"
              ></div>
            </div>
          </div>

          <!-- Biggest Expense Categories for this specific wallet -->
          <div>
            <h4 style="font-size: 0.95rem; margin: 0 0 0.65rem 0;">
              🏷️ Biggest Expense Categories for this Wallet
            </h4>
            <div v-if="!insightsData.top_categories.length" class="muted" style="font-size: 0.85rem;">
              No categorized expenses recorded from this account yet.
            </div>
            <div v-else class="category-spend-list">
              <div
                v-for="cat in insightsData.top_categories"
                :key="cat.category_id"
                class="category-spend-row"
              >
                <div class="category-spend-header">
                  <span><strong>{{ cat.name }}</strong> <small class="muted">{{ cat.budget_category ? `[${cat.budget_category}]` : '' }}</small></span>
                  <span>{{ money(cat.total_spent) }} <span class="muted">({{ cat.percentage }}%)</span></span>
                </div>
                <div class="category-progress-track">
                  <div class="category-progress-fill" :style="{ width: `${cat.percentage}%` }"></div>
                </div>
              </div>
            </div>
          </div>

          <!-- Recent Activity Statement for this Account -->
          <div>
            <div class="between" style="margin-bottom: 0.5rem;">
              <h4 style="font-size: 0.95rem; margin: 0;">📜 Recent Account Activity</h4>
              <span class="muted" style="font-size: 0.78rem;">Last 15 records</span>
            </div>

            <div v-if="!insightsData.recent_transactions.length" class="muted" style="font-size: 0.85rem;">
              No transactions on record for this account.
            </div>

            <ul v-else style="display: flex; flex-direction: column; gap: 0.4rem;">
              <li
                v-for="t in insightsData.recent_transactions"
                :key="t.id"
                style="padding: 0.55rem 0.85rem; font-size: 0.86rem;"
              >
                <div>
                  <strong>{{ t.narrative || t.category_name || t.kind }}</strong>
                  <small class="muted">
                    &bull; {{ t.date }}
                    <template v-if="t.kind === 'transfer'">
                      ({{ t.account === insightsAccount.id ? `To ${t.to_account_name || 'Account'}` : `From ${t.account_name || 'Account'}` }})
                    </template>
                    <template v-if="Number(t.fee) > 0"> &bull; Fee: {{ money(t.fee) }}</template>
                  </small>
                </div>
                <div :class="t.kind === 'income' || (t.kind === 'transfer' && t.to_account === insightsAccount.id) || (t.kind === 'adjustment' && t.adjustment_type === 'credit') ? 'tag-green' : 'neg'">
                  {{ (t.kind === 'income' || (t.kind === 'transfer' && t.to_account === insightsAccount.id) || (t.kind === 'adjustment' && t.adjustment_type === 'credit')) ? '+' : '-' }}{{ money(t.amount) }}
                </div>
              </li>
            </ul>
          </div>

          <!-- Bottom Action Buttons in Modal -->
          <div class="modal-footer" style="margin-top: 1rem;">
            <button class="btn-action-pill btn-reconcile" @click="showInsightsModal = false; openReconcileModal(insightsAccount)">
              ⚖️ Reconcile Account
            </button>
            <button class="btn-action-pill btn-transfer" @click="showInsightsModal = false; openTransferModal(insightsAccount)">
              🔁 Transfer Funds
            </button>
            <button class="btn-secondary-pill" @click="showInsightsModal = false">Close</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>