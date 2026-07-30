import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  hasTokens,
  onTokensCleared,
  setTokens,
} from "./tokenStore";

describe("tokenStore", () => {
  beforeEach(() => clearTokens());

  it("persists and reads tokens", () => {
    expect(hasTokens()).toBe(false);
    setTokens({ accessToken: "a", refreshToken: "r" });
    expect(getAccessToken()).toBe("a");
    expect(getRefreshToken()).toBe("r");
    expect(hasTokens()).toBe(true);
    expect(localStorage.getItem("blackbox.accessToken")).toBe("a");
  });

  it("clears tokens and notifies subscribers", () => {
    const listener = vi.fn();
    const unsub = onTokensCleared(listener);
    setTokens({ accessToken: "a", refreshToken: "r" });

    clearTokens();

    expect(getAccessToken()).toBeNull();
    expect(hasTokens()).toBe(false);
    expect(listener).toHaveBeenCalledTimes(1);
    unsub();
  });
});
