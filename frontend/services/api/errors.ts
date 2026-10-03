export type ApiErrorKind =
  /** The server could not be reached (DNS, refused connection, CORS rejection). */
  | "network"
  /** No response within the timeout. */
  | "timeout"
  /** The caller cancelled the request. */
  | "aborted"
  /** The server replied with a non-success HTTP status. */
  | "http"
  /** The server replied, but the body did not match the expected contract. */
  | "malformed";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;
  /** Backend error code from the ErrorResponse contract, e.g. "validation_error". */
  readonly code?: string;
  readonly requestId?: string;

  constructor(
    kind: ApiErrorKind,
    message: string,
    options: { status?: number; code?: string; requestId?: string; cause?: unknown } = {},
  ) {
    super(message, { cause: options.cause });
    this.name = "ApiError";
    this.kind = kind;
    this.status = options.status;
    this.code = options.code;
    this.requestId = options.requestId;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}
