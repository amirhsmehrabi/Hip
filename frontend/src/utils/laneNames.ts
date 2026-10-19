/**
 * Short labels for a set of lane names shown side by side. Stems of one track are named
 * "<track>: <stem>", so a chip that truncates the tail shows only the track, the same for all;
 * this drops the beginning they share and keeps the part that tells them apart.
 * Names with nothing in common come back as they are.
 */
export function shortLaneNames(names: string[]): string[] {
  if (names.length < 2) return [...names]
  let prefix = names[0]
  for (const n of names.slice(1)) {
    let i = 0
    while (i < prefix.length && i < n.length && prefix[i] === n[i]) i++
    prefix = prefix.slice(0, i)
  }
  // Cut back to a separator so the remainder starts on a word, not mid-word.
  const cut = Math.max(prefix.lastIndexOf(': '), prefix.lastIndexOf(' - '), prefix.lastIndexOf(' · '), prefix.lastIndexOf(' / '))
  if (cut <= 0) return [...names]
  const sepLen = prefix[cut] === ':' ? 2 : 3
  const short = names.map((n) => n.slice(cut + sepLen).trim())
  return short.every((s) => s.length > 0) ? short : [...names]
}
