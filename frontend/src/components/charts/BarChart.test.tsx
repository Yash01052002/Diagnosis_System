import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { BarChart } from "./BarChart";

describe("BarChart", () => {
  it("renders a labelled bar per datum with humanized labels", () => {
    render(
      <BarChart
        data={[
          { label: "hard_fault", value: 7 },
          { label: "bus_fault", value: 3 },
        ]}
      />,
    );
    expect(screen.getByText("Hard Fault")).toBeInTheDocument();
    expect(screen.getByText("Bus Fault")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("shows the empty label when there is no data", () => {
    render(<BarChart data={[]} emptyLabel="Nothing here" />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
  });

  it("keeps raw labels when humanizeLabels is false", () => {
    render(<BarChart data={[{ label: "1.4.2", value: 5 }]} humanizeLabels={false} />);
    expect(screen.getByText("1.4.2")).toBeInTheDocument();
  });
});
