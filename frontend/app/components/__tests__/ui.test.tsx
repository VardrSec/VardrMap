import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// react-markdown / remark-gfm are ESM-only; mock them so importing ui.tsx does
// not pull real ESM into the CommonJS Jest runtime. The mock renders the raw
// markdown text, which is all the preview assertions below need.
jest.mock("react-markdown", () => ({
  __esModule: true,
  default: ({ children }: { children: string }) => children,
}));
jest.mock("remark-gfm", () => ({ __esModule: true, default: () => {} }));

import {
  SeverityBadge,
  StatusBadge,
  PrimaryButton,
  DangerButton,
  Input,
  SelectField,
  Textarea,
  ListCard,
} from "../ui";

describe("SeverityBadge", () => {
  it("colors a critical severity red and shows its label", () => {
    render(<SeverityBadge severity="critical" />);
    const badge = screen.getByText("critical");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass("text-red-400");
  });

  it("colors high orange", () => {
    render(<SeverityBadge severity="high" />);
    expect(screen.getByText("high")).toHaveClass("text-orange-400");
  });

  it("is case-insensitive on the severity value", () => {
    render(<SeverityBadge severity="CRITICAL" />);
    // Label preserves the original casing; color mapping is lowercased.
    expect(screen.getByText("CRITICAL")).toHaveClass("text-red-400");
  });

  it("falls back to 'info' for an empty severity and does not use a severity color", () => {
    render(<SeverityBadge severity="" />);
    const badge = screen.getByText("info");
    expect(badge).toBeInTheDocument();
    expect(badge).not.toHaveClass("text-red-400");
  });
});

describe("StatusBadge", () => {
  it("renders underscores as spaces and colors validated emerald", () => {
    render(<StatusBadge status="validated" />);
    expect(screen.getByText("validated")).toHaveClass("text-emerald-400");
  });

  it("humanizes a snake_case status", () => {
    render(<StatusBadge status="in_progress" />);
    const badge = screen.getByText("in progress");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass("text-blue-400");
  });

  it("renders an em dash for an empty status", () => {
    render(<StatusBadge status="" />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

describe("buttons", () => {
  it("PrimaryButton calls onClick when clicked", async () => {
    const onClick = jest.fn();
    render(<PrimaryButton label="Save" onClick={onClick} />);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("DangerButton renders its label and calls onClick", async () => {
    const onClick = jest.fn();
    render(<DangerButton label="Delete" onClick={onClick} />);
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe("Input", () => {
  it("calls onChange with the typed character", async () => {
    const onChange = jest.fn();
    render(<Input label="Name" value="" onChange={onChange} />);
    await userEvent.type(screen.getByRole("textbox"), "x");
    expect(onChange).toHaveBeenCalledWith("x");
  });
});

describe("SelectField", () => {
  it("renders its options and reports the selected value", async () => {
    const onChange = jest.fn();
    render(<SelectField label="Severity" value="low" options={["low", "high"]} onChange={onChange} />);
    expect(screen.getByRole("option", { name: "low" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "high" })).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole("combobox"), "high");
    expect(onChange).toHaveBeenCalledWith("high");
  });
});

describe("Textarea", () => {
  it("starts in edit mode showing the textarea", () => {
    render(<Textarea label="Notes" value="hello" onChange={jest.fn()} />);
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("switches to preview, hiding the textarea and rendering the markdown text", async () => {
    render(<Textarea label="Notes" value="hello world" onChange={jest.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "preview" }));
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByText("hello world")).toBeInTheDocument();
  });

  it("shows an empty-state message when previewing blank content", async () => {
    render(<Textarea label="Notes" value="   " onChange={jest.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "preview" }));
    expect(screen.getByText("Nothing to preview.")).toBeInTheDocument();
  });
});

describe("ListCard", () => {
  it("renders title and subtitle and fires onDelete", async () => {
    const onDelete = jest.fn();
    render(<ListCard title="My Item" subtitle="a subtitle" onDelete={onDelete} />);
    expect(screen.getByText("My Item")).toBeInTheDocument();
    expect(screen.getByText("a subtitle")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalledTimes(1);
  });
});
