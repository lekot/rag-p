import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const mockPush = vi.fn();
const mockReplace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
}));

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

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
  });

  it("shows 'not authenticated' when useUser returns null", async () => {
    vi.mock("@/lib/auth", () => ({
      useUser: () => null,
    }));
    vi.mock("@/lib/trpc", () => ({
      trpc: {
        keys: {
          list: { useQuery: () => ({ data: [], isLoading: false }) },
          delete: {
            useMutation: () => ({ mutateAsync: vi.fn(), isPending: false }),
          },
          create: {
            useMutation: () => ({ mutateAsync: vi.fn(), isPending: false }),
          },
        },
        useUtils: () => ({
          keys: { list: { invalidate: vi.fn() } },
        }),
      },
    }));

    const { default: AccountPage } = await import("@/app/account/page");
    render(<AccountPage />);

    expect(screen.getByText(/not authenticated/i)).toBeTruthy();
  });

  it("shows profile info when user is present", async () => {
    vi.doMock("@/lib/auth", () => ({
      useUser: () => ({
        user: { id: "u1", email: "test@example.com" },
        organization: { id: "o1", name: "Acme", slug: "acme", role: "admin" },
      }),
    }));
    vi.doMock("@/lib/trpc", () => ({
      trpc: {
        keys: {
          list: {
            useQuery: () => ({
              data: [
                {
                  id: "k1",
                  name: "prod",
                  key_prefix: "rgp_abcd",
                  created_at: "2024-01-01T00:00:00Z",
                  last_used_at: null,
                },
              ],
              isLoading: false,
            }),
          },
          delete: {
            useMutation: () => ({ mutateAsync: vi.fn(), isPending: false }),
          },
          create: {
            useMutation: () => ({ mutateAsync: vi.fn(), isPending: false }),
          },
        },
        useUtils: () => ({
          keys: { list: { invalidate: vi.fn() } },
        }),
      },
    }));

    // Re-import with mocks applied
    vi.resetModules();
    vi.doMock("@/lib/auth", () => ({
      useUser: () => ({
        user: { id: "u1", email: "test@example.com" },
        organization: { id: "o1", name: "Acme", slug: "acme", role: "admin" },
      }),
    }));
    vi.doMock("@/lib/trpc", () => ({
      trpc: {
        keys: {
          list: {
            useQuery: () => ({
              data: [],
              isLoading: false,
            }),
          },
          delete: {
            useMutation: () => ({ mutateAsync: vi.fn(), isPending: false }),
          },
          create: {
            useMutation: () => ({ mutateAsync: vi.fn(), isPending: false }),
          },
        },
        useUtils: () => ({
          keys: { list: { invalidate: vi.fn() } },
        }),
      },
    }));
    const mod = await import("@/app/account/page");
    render(<mod.default />);

    expect(screen.getByText(/test@example\.com/)).toBeTruthy();
  });
});
