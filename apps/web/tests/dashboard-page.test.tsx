import { readFileSync } from "node:fs";
import { join } from "node:path";
import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import DashboardPage from "@/app/page";

describe("DashboardPage", () => {
  it("server-renders dashboard links", () => {
    const html = renderToString(<DashboardPage />);

    expect(html).toContain("View Pipelines");
    expect(html).toContain("View Experiments");
    expect(html).toContain("View Datasets");
  });

  it("does not render Next links through Radix Slot on the server", () => {
    const source = readFileSync(join(__dirname, "../src/app/page.tsx"), "utf8");

    expect(source).not.toContain("asChild");
  });
});
