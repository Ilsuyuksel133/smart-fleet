import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CategoryBadge } from "./CategoryBadge";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("styles known statuses", () => {
    render(<StatusBadge status="ERROR" />);
    expect(screen.getByText("ERROR")).toHaveClass("badge-bad");
  });

  it("does not break on unknown or empty values", () => {
    render(<StatusBadge status="MAINTENANCE" />);
    expect(screen.getByText("MAINTENANCE")).toHaveClass("badge-neutral");
    render(<StatusBadge status="" />);
    expect(screen.getByText("unknown")).toBeInTheDocument();
  });
});

describe("CategoryBadge", () => {
  it("shows a readable category", () => {
    render(<CategoryBadge category="service_down" />);
    expect(screen.getByText(/service down/)).toBeInTheDocument();
  });

  it("does not break on unknown or missing values", () => {
    render(<CategoryBadge category="disk_full" />);
    expect(screen.getByText(/disk full/)).toBeInTheDocument();
    render(<CategoryBadge category={null} />);
    expect(screen.getByText("pending")).toBeInTheDocument();
  });
});
