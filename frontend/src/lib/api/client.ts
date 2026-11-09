import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./schema";

/** Shapes from FastAPI's OpenAPI spec (regenerate with `pnpm api:types`). */
export type Schemas = components["schemas"];

/**
 * Typed client for the FastAPI backend. Requests go to /api/*, which
 * next.config.ts forwards to FastAPI, so the session cookie is same-origin.
 */
export const api = createClient<paths>({ baseUrl: "/api", credentials: "same-origin" });

/** Raised for any non-2xx answer, carrying FastAPI's `detail`. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(detailText(detail) ?? `Request failed (${status}).`);
  }
}

function detailText(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    // Pydantic validation errors: [{loc, msg}, ...]
    return detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
      .join("; ");
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message);
  }
  return null;
}

let onUnauthorized: (() => void) | null = null;

/** The auth provider registers this: a 401 anywhere outside /auth means the session ended. */
export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

const sessionWatch: Middleware = {
  onResponse({ request, response }) {
    if (response.status === 401 && !new URL(request.url).pathname.startsWith("/api/auth/")) {
      onUnauthorized?.();
    }
  },
};
api.use(sessionWatch);

/**
 * Unwraps an openapi-fetch result: returns the data, or throws ApiError.
 * `call(api.GET("/vendors"))`.
 */
export async function call<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await request;
  if (!response.ok) {
    const detail = error && typeof error === "object" && "detail" in error ? (error as { detail: unknown }).detail : error;
    throw new ApiError(response.status, detail);
  }
  return data as T;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
