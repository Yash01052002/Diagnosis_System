import { describe, expect, it } from "vitest";
import { humanize, percent, toHex } from "./format";

describe("toHex", () => {
  it("pads to a 32-bit 0x address", () => {
    expect(toHex(0x08001a2c)).toBe("0x08001A2C");
    expect(toHex(0)).toBe("0x00000000");
  });
  it("returns an em dash for nullish values", () => {
    expect(toHex(null)).toBe("—");
    expect(toHex(undefined)).toBe("—");
  });
});

describe("humanize", () => {
  it("title-cases snake_case", () => {
    expect(humanize("hard_fault")).toBe("Hard Fault");
    expect(humanize("stack_overflow")).toBe("Stack Overflow");
  });
  it("handles empty input", () => {
    expect(humanize("")).toBe("—");
    expect(humanize(null)).toBe("—");
  });
});

describe("percent", () => {
  it("rounds a 0-1 score to a percentage", () => {
    expect(percent(0.412)).toBe("41%");
    expect(percent(1)).toBe("100%");
  });
  it("returns an em dash for nullish values", () => {
    expect(percent(null)).toBe("—");
  });
});
