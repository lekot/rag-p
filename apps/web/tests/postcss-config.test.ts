import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const appRoot = join(__dirname, "..");
const requireFromApp = createRequire(join(appRoot, "package.json"));

describe("PostCSS config", () => {
  it("uses a Next-compatible CommonJS config with Tailwind and Autoprefixer", () => {
    expect(existsSync(join(appRoot, "postcss.config.cjs"))).toBe(true);
    expect(existsSync(join(appRoot, "postcss.config.mjs"))).toBe(false);

    const config = requireFromApp("./postcss.config.cjs");

    expect(config).toEqual({
      plugins: {
        tailwindcss: {},
        autoprefixer: {},
      },
    });
  });
});
