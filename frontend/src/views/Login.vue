<script setup>
import { ref } from 'vue'
import { api } from '../api'

defineProps({
  theme: {
    type: String,
    default: 'dark'
  }
})

const emit = defineEmits(['in', 'toggleTheme'])
const mode = ref('login')
const u = ref('')
const p = ref('')
const err = ref('')
const loading = ref(false)

async function go() {
  err.value = ''
  loading.value = true
  try {
    const r = await api(mode.value + '/', 'POST', { username: u.value, password: p.value })
    localStorage.t = r.token
    emit('in')
  } catch (e) {
    err.value = e?.error || 'Check your username and password.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-card">
    <div class="login-top-bar">
      <button
        class="theme-mini-btn"
        :title="theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'"
        @click="emit('toggleTheme')"
      >
        {{ theme === 'dark' ? '☀️' : '🌙' }}
      </button>
    </div>

    <div class="brand-badge">S</div>
    <h1 class="login-title">Tally Portal</h1>
    <p class="login-subtitle">Know what is left before you spend it</p>

    <form class="login-form" @submit.prevent="go">
      <div class="form-group">
        <label class="form-label">Username</label>
        <input
          v-model="u"
          class="form-input"
          placeholder="Enter username"
          required
          autocomplete="username"
          autofocus
        />
      </div>

      <div class="form-group">
        <label class="form-label">Password</label>
        <input
          v-model="p"
          type="password"
          class="form-input"
          placeholder="Enter password"
          required
          autocomplete="current-password"
        />
      </div>

      <p v-if="err" class="login-error">{{ err }}</p>

      <button type="submit" class="btn-orange-pill login-submit" :disabled="loading">
        {{ loading ? 'Please wait...' : (mode === 'login' ? 'Sign In' : 'Create Account') }}
      </button>
    </form>

    <div class="login-toggle">
      <button class="toggle-link" @click="mode = mode === 'login' ? 'register' : 'login'">
        {{ mode === 'login' ? 'New here? Create an account' : 'Have an account? Sign in' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.login-card {
  width: 100%;
  max-width: 400px;
  background: var(--bg-card);
  border: 1px solid var(--border-card);
  border-radius: var(--radius-card);
  padding: 2.25rem 2rem;
  box-shadow: var(--shadow-modal);
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
  transition: background-color 0.2s ease, border-color 0.2s ease;
}

.login-top-bar {
  position: absolute;
  top: 1rem;
  right: 1rem;
}

.theme-mini-btn {
  background: var(--bg-input);
  border: 1px solid var(--border-input);
  border-radius: 50%;
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 1rem;
  transition: all 0.15s ease;
}

.theme-mini-btn:hover {
  border-color: var(--accent-orange);
  transform: scale(1.05);
}

.brand-badge {
  width: 50px;
  height: 50px;
  border-radius: 50%;
  background: var(--accent-orange);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 1.4rem;
  box-shadow: 0 4px 14px rgba(255, 107, 0, 0.4);
  margin-bottom: 1.25rem;
}

.login-title {
  margin: 0 0 0.4rem;
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--text-primary);
}

.login-subtitle {
  margin: 0 0 1.75rem;
  color: var(--text-secondary);
  font-size: 0.9rem;
  text-align: center;
}

.login-form {
  width: 100%;
  display: flex;
  flex-direction: column;
}

.login-submit {
  width: 100%;
  justify-content: center;
  padding: 0.75rem;
  font-size: 0.95rem;
  margin-top: 0.75rem;
}

.login-error {
  color: var(--text-danger);
  font-size: 0.85rem;
  margin: 0 0 0.75rem;
}

.login-toggle {
  margin-top: 1.5rem;
  text-align: center;
}

.toggle-link {
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 0.88rem;
  cursor: pointer;
  text-decoration: underline;
  transition: color 0.15s;
}

.toggle-link:hover {
  color: var(--accent-orange);
}
</style>
