import type { TransactionType } from "../api/types";

/** Plain, past-tense names for portfolio events. */
export const activityLabels: Record<TransactionType, string> = {
  buy: "Bought",
  sell: "Sold",
  dividend: "Dividend",
  deposit: "Deposit",
  withdrawal: "Withdrawal",
  fee: "Fee",
  other: "Other",
};
