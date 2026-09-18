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
  const isFormData = init?.body instanceof FormData;
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(!isFormData ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new ApiError(response.status, errorMessage(body));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function streamApi(
  path: string,
  body: unknown,
  onEvent: (event: string, data: Record<string, unknown>) => void,
): Promise<void> {
  const response = await fetch(`${API_ROOT}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    throw new ApiError(response.status, errorMessage(payload));
  }
  if (!response.body) throw new Error("Streaming is not supported by this browser");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const event = block.match(/^event:\s*(.+)$/m)?.[1] ?? "message";
      const raw = block.match(/^data:\s*(.+)$/m)?.[1] ?? "{}";
      const data = JSON.parse(raw) as Record<string, unknown>;
      onEvent(event, data);
    }
    if (done) break;
  }
}

export async function downloadApi(path: string, init?: RequestInit): Promise<void> {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new ApiError(response.status, errorMessage(body));
  }

  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1]
    ?? "northstar-export.json";
  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
