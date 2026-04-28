import { z } from "zod";

const envSchema = z.object({
  NEXT_PUBLIC_API_URL: z
    .string()
    .url()
    .default("http://localhost:8000"),
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- process.env is untyped
export const env = envSchema.parse(process.env as any);
