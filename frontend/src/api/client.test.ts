import { describe, expect, it } from "vitest";
import { AxiosError, AxiosHeaders } from "axios";
import { errorMessage, toApiError } from "./client";

function axiosErrorWith(status: number, data: unknown): AxiosError {
  const err = new AxiosError("Request failed", "ERR_BAD_REQUEST");
  err.response = {
    status,
    statusText: "Error",
    data,
    headers: {},
    config: { headers: new AxiosHeaders() },
  };
  return err;
}

describe("toApiError", () => {
  it("unwraps the server error envelope", () => {
    const err = axiosErrorWith(404, {
      error: { code: "not_found", message: "Crash report not found." },
    });
    expect(toApiError(err)).toEqual({
      code: "not_found",
      message: "Crash report not found.",
    });
  });

  it("falls back to a status code when there is no envelope", () => {
    const err = axiosErrorWith(500, "boom");
    expect(toApiError(err).code).toBe("http_500");
  });

  it("reports a network error when there is no response", () => {
    const err = new AxiosError("Network Error", "ERR_NETWORK");
    expect(toApiError(err).code).toBe("network_error");
  });

  it("handles non-axios errors", () => {
    expect(toApiError(new Error("nope")).code).toBe("unknown");
  });
});

describe("errorMessage", () => {
  it("returns the human message", () => {
    const err = axiosErrorWith(409, {
      error: { code: "conflict", message: "Already exists." },
    });
    expect(errorMessage(err)).toBe("Already exists.");
  });
});
