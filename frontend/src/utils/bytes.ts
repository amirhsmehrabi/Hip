/** "4,8" / "4.8": gigabytes with one decimal in the locale's digits; the unit is the caller's (a translated string). */
export function gb(bytes: number, locale: string): string {
  return new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(bytes / 1e9)
}
