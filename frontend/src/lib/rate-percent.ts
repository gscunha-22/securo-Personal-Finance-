/** Engine treats 14 as 14% a.m. Values like 0.0399 are 0.0399% a.m., not 3.99%. */
export function looksLikeRateFraction(raw: string): boolean {
  const value = Number(raw)
  return Number.isFinite(value) && value > 0 && value < 1
}
