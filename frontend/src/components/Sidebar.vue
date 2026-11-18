<script setup>
defineProps({
  currentTab: {
    type: String,
    required: true
  },
  tabs: {
    type: Array,
    required: true
  },
  theme: {
    type: String,
    default: 'dark'
  }
})

const emit = defineEmits(['selectTab', 'signOut', 'toggleTheme'])
</script>

<template>
  <aside class="sidebar">
    <!-- Brand / Logo -->
    <div class="sidebar-brand">
      <div class="brand-avatar">S</div>
      <div class="brand-text">
        <span class="brand-title">Tally Portal</span>
      </div>
    </div>

    <!-- Navigation Menu -->
    <nav class="sidebar-nav">
      <button
        v-for="item in tabs"
        :key="item.id"
        class="nav-item"
        :class="{ active: currentTab === item.id }"
        @click="emit('selectTab', item.id)"
      >
        <span class="nav-label">{{ item.label }}</span>
      </button>
    </nav>

    <!-- Sidebar Footer -->
    <div class="sidebar-footer">
      <!-- Theme Switcher Toggle -->
      <button
        class="theme-toggle-btn"
        :title="theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'"
        @click="emit('toggleTheme')"
      >
        <span class="theme-icon">{{ theme === 'dark' ? '☀️' : '🌙' }}</span>
        <span class="theme-text">{{ theme === 'dark' ? 'Light Mode' : 'Dark Mode' }}</span>
      </button>

      <div class="footer-row">
        <div class="version-text">Budget Management v1.0</div>
        <button class="sign-out-btn" @click="emit('signOut')">
          Sign out
        </button>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 250px;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border-sidebar);
  display: flex;
  flex-direction: column;
  padding: 1.5rem 1.25rem;
  flex-shrink: 0;
  min-height: 100vh;
  transition: background-color 0.2s ease, border-color 0.2s ease;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  padding: 0.5rem 0.5rem 1.75rem 0.5rem;
}

.brand-avatar {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: var(--accent-orange);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 1.15rem;
  box-shadow: 0 4px 10px rgba(255, 107, 0, 0.35);
}

.brand-text {
  display: flex;
  flex-direction: column;
}

.brand-title {
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.01em;
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  flex: 1;
}

.nav-item {
  width: 100%;
  text-align: left;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 0.95rem;
  font-weight: 500;
  padding: 0.7rem 1.25rem;
  border-radius: var(--radius-pill);
  cursor: pointer;
  transition: all 0.18s ease;
  display: flex;
  align-items: center;
}

.nav-item:hover:not(.active) {
  background: var(--hover-subtle);
  color: var(--text-primary);
}

.nav-item.active {
  background: var(--accent-orange);
  color: #ffffff;
  font-weight: 600;
  box-shadow: 0 4px 12px rgba(255, 107, 0, 0.3);
}

.sidebar-footer {
  padding-top: 1.25rem;
  border-top: 1px solid var(--divider-subtle);
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

/* Theme Toggle Button */
.theme-toggle-btn {
  width: 100%;
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-pill);
  padding: 0.55rem 1rem;
  color: var(--text-primary);
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  box-shadow: var(--shadow-card);
  transition: all 0.15s ease;
}

.theme-toggle-btn:hover {
  background: var(--hover-subtle);
  border-color: var(--accent-orange);
}

.theme-icon {
  font-size: 1rem;
  line-height: 1;
}

.footer-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.version-text {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.sign-out-btn {
  background: transparent;
  border: 1px solid var(--border-input);
  border-radius: var(--radius-pill);
  color: var(--text-secondary);
  padding: 0.3rem 0.8rem;
  font-size: 0.78rem;
  cursor: pointer;
  transition: all 0.15s;
}

.sign-out-btn:hover {
  background: rgba(239, 68, 68, 0.12);
  color: var(--text-danger);
  border-color: rgba(239, 68, 68, 0.3);
}
</style>
