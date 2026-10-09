// Presentation only: every value formatted here arrives ready-made from the API.

export const shortAddress = (address) => `${address.slice(0, 6)}…${address.slice(-4)}`;

export const signed = (n) => (n > 0 ? `+${n}` : n < 0 ? `-${Math.abs(n)}` : "±0");

export const direction = (n) => (n > 0 ? "up" : n < 0 ? "down" : "flat");

export const clockTime = (iso) => (iso ? iso.slice(11, 19) : "");

// MM-DD HH:MM:SS -- chain time; the demo chain runs ahead of the wall clock.
export const chainStamp = (iso) => (iso ? `${iso.slice(5, 10)} ${iso.slice(11, 19)}` : "");

export const usd = (value) =>
  "$" + Number(value).toLocaleString("en-US", { maximumFractionDigits: 2 });

export const EVENT_LABELS = {
  job_completed: "clean settlement",
  dispute_won: "won dispute",
  dispute_lost: "lost dispute",
  payment_default: "payment default",
};

export const FEATURE_LABELS = {
  jobs_completed: "Jobs completed",
  dispute_rate: "Dispute rate",
  avg_job_value_usd: "Avg job value",
  account_age_days: "Account age",
  on_time_payment_rate: "Clean settlements",
  prior_defaults: "Prior defaults",
  counterparty_diversity: "Counterparties",
};
