import { z } from "zod";

const envSchema = z.object({
  NEXT_PUBLIC_API_URL: z
    .string()
    .url()
    .default("http://localhost:8000"),
  // TODO: временный fallback пока юзер не залогинился; после миграции UI на cookie-only удалить
  NEXT_PUBLIC_ORG_ID: z.string().default("00000000-0000-0000-0000-000000000001"),
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- process.env is untyped
export const env = envSchema.parse(process.env as any);
