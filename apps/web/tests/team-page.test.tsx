import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const mockPush = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

// Helper to mock auth + trpc for the team page.
function mockTrpc(opts: {
  members: Array<{ user_id: string; email: string; role: string; created_at: string }>;
  invites: Array<{
    id: string;
    email: string;
    role: string;
    created_at: string;
    expires_at: string;
    accepted_at: string | null;
  }>;
}) {
  const useMutation = () => ({
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    isPending: false,
  });
  vi.doMock("@/lib/trpc", () => ({
    trpc: {
      orgs: {
        listMembers: {
          useQuery: () => ({
            data: { members: opts.members },
            isLoading: false,
            isError: false,
            error: null,
          }),
        },
        listInvites: {
          useQuery: () => ({
            data: { invites: opts.invites },
            isLoading: false,
          }),
        },
        invite: { useMutation },
        revokeInvite: { useMutation },
        removeMember: { useMutation },
        changeRole: { useMutation },
      },
      useUtils: () => ({
        orgs: {
          listMembers: { invalidate: vi.fn(), cancel: vi.fn(), getData: vi.fn(), setData: vi.fn() },
          listInvites: { invalidate: vi.fn(), cancel: vi.fn(), getData: vi.fn(), setData: vi.fn() },
        },
      }),
    },
  }));
}

function mockUser(role: "owner" | "admin" | "member" | null) {
  if (role === null) {
    vi.doMock("@/lib/auth", () => ({ useUser: () => null }));
  } else {
    vi.doMock("@/lib/auth", () => ({
      useUser: () => ({
        user: { id: "u1", email: "me@example.com" },
        organization: { id: "o1", name: "Acme", slug: "acme", role },
      }),
    }));
  }
}

describe("TeamPage", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
  });

  it("redirects unauthenticated users to login prompt", async () => {
    mockUser(null);
    mockTrpc({ members: [], invites: [] });
    const { default: TeamPage } = await import("@/app/account/team/page");
    render(<TeamPage />);
    expect(screen.getByText(/не авторизован/i)).toBeTruthy();
  });

  it("shows member list with role badges for owner viewer", async () => {
    mockUser("owner");
    mockTrpc({
      members: [
        { user_id: "u1", email: "me@example.com", role: "owner", created_at: "2024-01-01T00:00:00Z" },
        { user_id: "u2", email: "alice@example.com", role: "admin", created_at: "2024-01-02T00:00:00Z" },
        { user_id: "u3", email: "bob@example.com", role: "member", created_at: "2024-01-03T00:00:00Z" },
      ],
      invites: [],
    });
    const { default: TeamPage } = await import("@/app/account/team/page");
    render(<TeamPage />);

    expect(screen.getByText("me@example.com")).toBeTruthy();
    expect(screen.getByText("alice@example.com")).toBeTruthy();
    expect(screen.getByText("bob@example.com")).toBeTruthy();
    // Owner sees Invite button
    expect(screen.getByRole("button", { name: /пригласить/i })).toBeTruthy();
  });

  it("hides invite button for plain members", async () => {
    mockUser("member");
    mockTrpc({
      members: [
        { user_id: "u1", email: "me@example.com", role: "member", created_at: "2024-01-01T00:00:00Z" },
        { user_id: "u2", email: "alice@example.com", role: "owner", created_at: "2024-01-02T00:00:00Z" },
      ],
      invites: [],
    });
    const { default: TeamPage } = await import("@/app/account/team/page");
    render(<TeamPage />);

    expect(screen.queryByRole("button", { name: /пригласить/i })).toBeNull();
  });

  it("renders pending invites section for admin", async () => {
    mockUser("admin");
    mockTrpc({
      members: [
        { user_id: "u1", email: "me@example.com", role: "admin", created_at: "2024-01-01T00:00:00Z" },
      ],
      invites: [
        {
          id: "inv1",
          email: "pending@example.com",
          role: "member",
          created_at: "2024-01-04T00:00:00Z",
          expires_at: "2024-01-11T00:00:00Z",
          accepted_at: null,
        },
      ],
    });
    const { default: TeamPage } = await import("@/app/account/team/page");
    render(<TeamPage />);

    expect(screen.getByText(/ожидающие приглашения/i)).toBeTruthy();
    expect(screen.getByText("pending@example.com")).toBeTruthy();
    expect(screen.getByRole("button", { name: /отозвать/i })).toBeTruthy();
  });
});
