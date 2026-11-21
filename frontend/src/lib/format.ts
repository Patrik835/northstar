// One way to show money and change across the app: € values, +/− signs, green/red tones.

const eurCents = new Intl.NumberFormat("en-IE", {
  style: "currency", currency: "EUR", minimumFractionDigits: 2, maximumFractionDigits: 2,
});
const eurWhole = new Intl.NumberFormat("en-IE", {
  style: "currency", currency: "EUR", maximumFractionDigits: 0,
});

/** € amount; €100 or more drops the cents so amounts side by side look alike. */
export function formatEur(value: number): string {
  return (Math.abs(value) >= 100 ? eurWhole : eurCents).format(value);
}

/** Gain/loss in €, always with a sign: +€120.50 / −€80.00. */
export function formatChange(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${formatEur(Math.abs(value))}`;
}

/** Percentage change with a sign: +4.2% / −1.8%. */
export function formatPercentChange(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(Math.abs(value) >= 100 ? 0 : 1)}%`;
}

/** CSS class for a gain/loss value (styled globally as green/red). */
export function tone(value: number): "positive" | "negative" | "neutral" {
  return value > 0 ? "positive" : value < 0 ? "negative" : "neutral";
}
