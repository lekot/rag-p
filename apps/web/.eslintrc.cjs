/** @type {import("eslint").Linter.Config} */
const config = {
  extends: ["next/core-web-vitals"],
  parser: "@typescript-eslint/parser",
  plugins: ["@typescript-eslint"],
  rules: {
    "@typescript-eslint/no-unused-vars": [
      "error",
      { argsIgnorePattern: "^_", varsIgnorePattern: "^_|Schema$" },
    ],
    "@typescript-eslint/no-explicit-any": "warn",
  },
};

module.exports = config;
