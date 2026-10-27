import { createI18n } from 'vue-i18n'
import ru from '../locales/ru'
import en from '../locales/en'
import ar from '../locales/ar'

export type LocaleCode = 'ru' | 'en' | 'ar'
export const LOCALES: { code: LocaleCode; name: string; rtl?: boolean }[] = [
  { code: 'ru', name: 'Русский' },
  { code: 'en', name: 'English' },
  { code: 'ar', name: 'العربية', rtl: true },
]
const isLocale = (code: unknown): code is LocaleCode => LOCALES.some((l) => l.code === code)
const STORAGE_KEY = 'remiqora_locale'

// The interface follows the system language until the user picks one. Any Russian among the preferred languages
// counts: people in Ukraine, Belarus or Kazakhstan often list uk/be/kk first and ru second.
function systemLocale(): LocaleCode {
  const preferred = navigator.languages?.length ? navigator.languages : [navigator.language ?? '']
  if (preferred.some((lang) => lang.toLowerCase().startsWith('ru'))) return 'ru'
  return preferred.some((lang) => lang.toLowerCase().startsWith('ar')) ? 'ar' : 'en'
}

// The document language and reading direction follow the interface language.
function applyDocumentLocale(locale: LocaleCode) {
  document.documentElement.lang = locale
  document.documentElement.dir = LOCALES.find((l) => l.code === locale)?.rtl ? 'rtl' : 'ltr'
}

function detectInitialLocale(): LocaleCode {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (isLocale(saved)) return saved
  } catch {
    // localStorage unavailable (private browsing) - fall through to the system language.
  }
  return systemLocale()
}

const initialLocale = detectInitialLocale()
applyDocumentLocale(initialLocale)

export const i18n = createI18n({
  legacy: false,
  locale: initialLocale,
  // A language that is only partly translated shows English for the rest.
  fallbackLocale: { ar: ['en'], default: ['ru'] },
  messages: { ru, en, ar },
})

export function setLocale(locale: LocaleCode) {
  ;(i18n.global.locale as any).value = locale
  applyDocumentLocale(locale)
  try {
    localStorage.setItem(STORAGE_KEY, locale)
  } catch {
    // ignore - just won't persist across reloads
  }
}

export function currentLocale(): LocaleCode {
  return (i18n.global.locale as any).value
}
