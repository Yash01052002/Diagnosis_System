import { describe, expect, it } from "vitest";
import { confidenceColor, severityColor } from "./chartColors";

describe("severityColor", () => {
  it("maps severities to reserved status hues", () => {
    expect(severityColor("critical")).toBe("var(--chart-critical)");
    expect(severityColor("high")).toBe("var(--chart-serious)");
    expect(severityColor("medium")).toBe("var(--chart-warning)");
    expect(severityColor("low")).toBe("var(--chart-muted)");
  });
  it("falls back to the series hue for unknown values", () => {
    expect(severityColor("weird")).toBe("var(--chart-series-1)");
  });
});

describe("confidenceColor", () => {
  it("maps confidence labels to tones", () => {
    expect(confidenceColor("certain")).toBe("var(--chart-good)");
    expect(confidenceColor("likely")).toBe("var(--chart-series-1)");
    expect(confidenceColor("uncertain")).toBe("var(--chart-warning)");
  });
});
