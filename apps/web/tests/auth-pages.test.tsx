import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const mockPush = vi.fn();
const mockReplace = vi.fn();
const mockLocationAssign = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
  useSearchParams: () => new URLSearchParams(),
}));

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

const trpcMocks = vi.hoisted(() => ({
  useUser: vi.fn(),
  keysListUseQuery: vi.fn(),
  keysCreateMutateAsync: vi.fn(),
  keysDeleteMutateAsync: vi.fn(),
  keysInvalidate: vi.fn(),
  billingGetUseQuery: vi.fn(),
  billingSubscriptionUseQuery: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({
  useUser: trpcMocks.useUser,
}));

vi.mock("@/lib/trpc", () => ({
  trpc: {
    keys: {
      list: { useQuery: trpcMocks.keysListUseQuery },
      delete: {
        useMutation: () => ({
          mutateAsync: trpcMocks.keysDeleteMutateAsync,
          isPending: false,
        }),
      },
      create: {
        useMutation: () => ({
          mutateAsync: trpcMocks.keysCreateMutateAsync,
          isPending: false,
        }),
      },
    },
    billing: {
      get: { useQuery: trpcMocks.billingGetUseQuery },
      subscription: { useQuery: trpcMocks.billingSubscriptionUseQuery },
    },
    useUtils: () => ({
      keys: { list: { invalidate: trpcMocks.keysInvalidate } },
    }),
  },
}));

// ── Login page ───────────────────────────────────────────────────────────────
describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders email and password fields", async () => {
    const { default: LoginPage } = await import("@/app/login/page");
    render(<LoginPage />);

    expect(screen.getByLabelText(/email/i)).toBeTruthy();
    expect(screen.getByLabelText(/пароль/i)).toBeTruthy();
  });

  it("renders submit button", async () => {
    const { default: LoginPage } = await import("@/app/login/page");
    render(<LoginPage />);

    const btn = screen.getByRole("button", { name: /войти/i });
    expect(btn).toBeTruthy();
  });
});

// ── Signup page ──────────────────────────────────────────────────────────────
describe("SignupPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders email, password and org fields", async () => {
    const { default: SignupPage } = await import("@/app/signup/page");
    render(<SignupPage />);

    expect(screen.getByLabelText(/email/i)).toBeTruthy();
    expect(screen.getByLabelText(/пароль/i)).toBeTruthy();
    expect(screen.getByLabelText(/организации/i)).toBeTruthy();
  });

  it("renders submit button", async () => {
    const { default: SignupPage } = await import("@/app/signup/page");
    render(<SignupPage />);

    const btn = screen.getByRole("button", { name: /зарегистрироваться/i });
    expect(btn).toBeTruthy();
  });
});

// ── Account page ─────────────────────────────────────────────────────────────
describe("AccountPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(window, "location", {
      value: { assign: mockLocationAssign },
      configurable: true,
    });
    trpcMocks.keysListUseQuery.mockReturnValue({ data: [], isLoading: false });
    trpcMocks.keysCreateMutateAsync.mockResolvedValue({ key: "rgp_test" });
    trpcMocks.keysDeleteMutateAsync.mockResolvedValue(undefined);
    trpcMocks.billingGetUseQuery.mockReturnValue({
      data: { balance_usd: 0 },
      isLoading: false,
      isError: false,
    });
    trpcMocks.billingSubscriptionUseQuery.mockReturnValue({
      data: null,
      isLoading: false,
      isError: false,
    });
  });

  it("shows 'not authenticated' when useUser returns null", async () => {
    trpcMocks.useUser.mockReturnValue(null);

    const { default: AccountPage } = await import("@/app/account/page");
    render(<AccountPage />);

    expect(screen.getByText(/not authenticated/i)).toBeTruthy();
  });

  it("shows profile info when user is present", async () => {
    trpcMocks.useUser.mockReturnValue({
      user: { id: "u1", email: "test@example.com" },
      organization: { id: "o1", name: "Acme", slug: "acme", role: "admin" },
    });
    trpcMocks.keysListUseQuery.mockReturnValue({
      data: [
        {
          id: "k1",
          name: "prod",
          key_prefix: "rgp_abcd",
          scope: "read",
          expires_at: "2026-01-01T00:00:00Z",
          is_expired: false,
          created_at: "2024-01-01T00:00:00Z",
          last_used_at: null,
        },
      ],
      isLoading: false,
    });
    trpcMocks.billingGetUseQuery.mockReturnValue({
      data: { balance_usd: 2.5 },
      isLoading: false,
      isError: false,
    });
    trpcMocks.billingSubscriptionUseQuery.mockReturnValue({
      data: {
        status: "active",
        current_period_end: "2026-01-01T00:00:00Z",
        q_used: 10,
        q_limit: 100,
        storage_bytes_used: 1024,
        storage_bytes_limit: 1024 * 1024,
        plan: {
          name: "Pro",
          allow_overage: true,
        },
      },
      isLoading: false,
      isError: false,
    });
    const mod = await import("@/app/account/page");
    render(<mod.default />);

    expect(screen.getByText(/test@example\.com/)).toBeTruthy();
  });

  it("hard navigates to login after logout to clear auth cache", async () => {
    trpcMocks.useUser.mockReturnValue({
      user: { id: "u1", email: "test@example.com" },
      organization: { id: "o1", name: "Acme", slug: "acme", role: "admin" },
    });
    mockFetch.mockResolvedValue({ ok: true });

    const { default: AccountPage } = await import("@/app/account/page");
    render(<AccountPage />);

    fireEvent.click(screen.getByRole("button", { name: /Выйти/i }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith("/api/auth/logout", { method: "POST" });
      expect(mockLocationAssign).toHaveBeenCalledWith("/login");
    });
    expect(mockPush).not.toHaveBeenCalledWith("/login");
  });

  it("hard navigates to login after account deletion to clear auth cache", async () => {
    trpcMocks.useUser.mockReturnValue({
      user: { id: "u1", email: "test@example.com" },
      organization: { id: "o1", name: "Acme", slug: "acme", role: "admin" },
    });
    mockFetch.mockResolvedValue({ ok: true });

    const { default: AccountPage } = await import("@/app/account/page");
    render(<AccountPage />);

    fireEvent.click(screen.getByRole("button", { name: /Удалить аккаунт/i }));
    fireEvent.change(screen.getByPlaceholderText("УДАЛИТЬ"), {
      target: { value: "УДАЛИТЬ" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Удалить$/i }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith("/api/proxy/v1/users/me/delete", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      });
      expect(mockLocationAssign).toHaveBeenCalledWith("/login");
    });
    expect(mockPush).not.toHaveBeenCalledWith("/login");
  });
});
