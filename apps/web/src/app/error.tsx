"use client";

export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="max-w-2xl mx-auto py-12 space-y-3">
      <h1 className="text-3xl font-bold">Error</h1>
      <p className="text-sm font-mono whitespace-pre-wrap text-muted-foreground">
        {error.message}
      </p>
      <button
        onClick={() => reset()}
        className="inline-flex items-center justify-center text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 h-9 rounded-md px-3"
      >
        Retry
      </button>
    </div>
  );
}
