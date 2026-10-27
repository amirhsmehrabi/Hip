import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.css'
import App from './App.vue'
import router from './router'
import { i18n, ready } from './i18n'

// The starting language loads first; if that fails the app still starts, in English.
ready.catch(() => undefined).finally(() => createApp(App).use(createPinia()).use(router).use(i18n).mount('#app'))
