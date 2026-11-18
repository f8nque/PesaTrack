<script setup>
import { ref, computed, onMounted } from 'vue'
import Sidebar from './components/Sidebar.vue'
import Login from './views/Login.vue'
import Today from './views/Today.vue'
import Categories from './views/Categories.vue'
import Home from './views/Home.vue'
import Transactions from './views/Transactions.vue'
import Accounts from './views/Accounts.vue'
import Budget from './views/Budget.vue'
import Debts from './views/Debts.vue'

const tabComponents = {
  Today,
  Categories,
  Home,
  Transactions,
  Accounts,
  Budget,
  Debts
}

const navTabs = [
  { id: 'Today', label: "Today's Spends" },
  { id: 'Categories', label: 'Categories' },
  { id: 'Home', label: 'Dashboard' },
  { id: 'Transactions', label: 'Transactions' },
  { id: 'Accounts', label: 'Accounts' },
  { id: 'Budget', label: 'Budget Plan' },
  { id: 'Debts', label: 'Debts' }
]

const authed = ref(!!localStorage.t)
// Start with Today's Spends as requested
const currentTab = ref('Today')

// Theme management: 'dark' (default) or 'light'
const theme = ref(localStorage.theme || 'dark')

function applyTheme(val) {
  theme.value = val
  localStorage.theme = val
  document.documentElement.setAttribute('data-theme', val)
}

function toggleTheme() {
  applyTheme(theme.value === 'dark' ? 'light' : 'dark')
}

onMounted(() => {
  applyTheme(theme.value)
})

const activeComponent = computed(() => tabComponents[currentTab.value] || Today)

function signOut() {
  localStorage.removeItem('t')
  authed.value = false
}
</script>

<template>
  <div v-if="!authed" class="login-wrapper">
    <Login :theme="theme" @in="authed = true" @toggle-theme="toggleTheme" />
  </div>

  <div v-else class="app-container">
    <!-- Left Side Panel Navigation -->
    <Sidebar
      :current-tab="currentTab"
      :tabs="navTabs"
      :theme="theme"
      @select-tab="id => currentTab = id"
      @sign-out="signOut"
      @toggle-theme="toggleTheme"
    />

    <!-- Main Content Area -->
    <main class="main-content">
      <component :is="activeComponent" />
    </main>
  </div>
</template>

<style scoped>
.login-wrapper {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-app);
}
</style>
