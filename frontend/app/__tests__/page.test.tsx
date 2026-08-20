import "@testing-library/jest-dom";
import { screen } from "@testing-library/react";

jest.mock("next-auth/react", () => ({ signIn: jest.fn(), signOut: jest.fn() }));
jest.mock("../components/DashboardSection", () => function DashboardSection() { return <div>Dashboard content</div>; });
jest.mock("../components/ScopeSection", () => function ScopeSection() { return null; });
jest.mock("../components/OverviewSection", () => function OverviewSection() { return null; });
jest.mock("../components/ReviewSection", () => function ReviewSection() { return null; });
jest.mock("../components/FindingsSection", () => function FindingsSection() { return null; });
jest.mock("../components/ReportsSection", () => function ReportsSection() { return null; });
jest.mock("../components/SettingsSection", () => function SettingsSection() { return null; });

import { renderWithApp } from "../../test-utils/renderWithApp";
import { Engagement } from "../types";
import { AppShell } from "../page";

const engagement = {
  id: "eng-1",
  name: "Acme API assessment",
  scope: { in: [], out: [] },
} as unknown as Engagement;

const authenticatedState = {
  authLoading: false,
  session: { backendToken: "test-token", user: { username: "operator" } },
  engagements: [engagement],
  activeSection: "dashboard" as const,
};

describe("engagement selection shell", () => {
  it("hides new-engagement controls while an engagement is active", () => {
    renderWithApp(<AppShell />, {
      state: { ...authenticatedState, selectedEngagementId: engagement.id },
      overrides: { selectedEngagement: engagement },
    });

    expect(screen.getByRole("combobox", { name: "Active Engagement" })).toHaveValue(engagement.id);
    expect(screen.queryByText("New Engagement")).not.toBeInTheDocument();
  });

  it("shows new-engagement controls after choosing no active engagement", async () => {
    renderWithApp(<AppShell />, {
      state: { ...authenticatedState, selectedEngagementId: "" },
      overrides: { selectedEngagement: null },
    });

    expect(screen.getByRole("combobox", { name: "Active Engagement" })).toHaveValue("");
    expect(await screen.findByText("New Engagement")).toBeInTheDocument();
  });
});
