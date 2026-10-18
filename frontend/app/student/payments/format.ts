// Exact decimal strings stay strings: trim by characters, never through floating point.
export function readableRate(rate: string, fractionDigits = 10): string {
  const [whole, fraction = ""] = rate.split(".");
  return fraction ? `${whole}.${fraction.slice(0, fractionDigits)}` : whole;
}
