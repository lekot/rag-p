export function isPaymentRequiredError(error: unknown): boolean {
  const message =
    error instanceof Error ? error.message : typeof error === "string" ? error : "";
  return /\b402\b|payment required|active subscription|required subscription/i.test(message);
}

export const PAYWALL_TOAST = {
  title: "Plan required",
  description: "Choose an active plan at /pricing to continue.",
  variant: "destructive" as const,
};
