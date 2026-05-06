import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

describe("ForgotPasswordPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("submits through the same-origin proxy and keeps the form on API errors", async () => {
    mockFetch.mockResolvedValue({ ok: false, status: 404 });

    const { default: ForgotPasswordPage } = await import("@/app/forgot-password/page");
    render(<ForgotPasswordPage />);

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "max@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /отправить ссылку/i }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith("/api/proxy/v1/auth/forgot-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: "max@example.com" }),
      });
    });

    expect(screen.getByLabelText(/email/i)).toBeTruthy();
  });
});
