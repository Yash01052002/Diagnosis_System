import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SeverityBadge } from "./badges";

describe("SeverityBadge", () => {
  it("renders the severity label with a danger tone for critical", () => {
    render(<SeverityBadge value="critical" />);
    const badge = screen.getByText("critical");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toMatch(/red/);
  });

  it("uses a neutral tone for low severity", () => {
    render(<SeverityBadge value="low" />);
    expect(screen.getByText("low").className).toMatch(/slate/);
  });
});
