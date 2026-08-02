const API_ROOT = import.meta.env.VITE_API_URL ?? "/api/v1";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

type ValidationIssue = {
  loc?: Array<string | number>;
  msg?: string;
};

function errorMessage(body: unknown): string {
  if (!body || typeof body !== "object" || !("detail" in body)) {
    return "Something went wrong";
  }
  const detail = body.detail;
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return "Something went wrong";

  const messages = detail.flatMap((item: unknown) => {
    if (!item || typeof item !== "object") return [];
    const issue = item as ValidationIssue;
    const field = issue.loc
      ?.filter((part) => part !== "body")
      .map(String)
      .join(" → ")
      .replaceAll("_", " ");
    const reason = issue.msg?.replace(/^Value error, /, "");
    if (!reason) return [];
    return [field ? `${field}: ${reason}` : reason];
  });
  return messages.join(". ") || "The submitted information is invalid";
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new ApiError(response.status, errorMessage(body));
  }
  return response.json() as Promise<T>;
}
