const SEPARATORS = [': ', ' - ', ' · ', ' / ']

/** The name split at its last separator: ["T.a.t.u. …", "Барабаны"], or null when it has none. */
function splitHead(name: string): [string, string] | null {
  let best = -1
  let sep = ''
  for (const s of SEPARATORS) {
    const i = name.lastIndexOf(s)
    if (i > best) {
      best = i
      sep = s
    }
  }
  if (best <= 0) return null
  const tail = name.slice(best + sep.length).trim()
  // A bare number ("Луп · drums · 2") names nothing on its own: such a lane keeps its full name.
  return /\p{L}/u.test(tail) ? [name.slice(0, best), tail] : null
}

/**
 * Short labels for a set of lane names shown side by side. Stems of one track are named
 * "<track>: <stem>", so a chip that truncates the tail shows only the track, the same for all;
 * a name whose head (the part before its last separator) is shared with another lane keeps only
 * its tail. Other names, the full mix among them, come back as they are.
 */
export function shortLaneNames(names: string[]): string[] {
  const heads = new Map<string, number>()
  const split = names.map(splitHead)
  for (const s of split) if (s) heads.set(s[0], (heads.get(s[0]) ?? 0) + 1)
  return names.map((n, i) => {
    const s = split[i]
    return s && (heads.get(s[0]) ?? 0) > 1 ? s[1] : n
  })
}
