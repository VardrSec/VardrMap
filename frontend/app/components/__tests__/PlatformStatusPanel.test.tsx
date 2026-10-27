import "@testing-library/jest-dom";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
jest.mock("react-markdown", () => ({ __esModule:true, default:({children}:{children:string}) => children }));
jest.mock("remark-gfm", () => ({ __esModule:true, default:() => {} }));

import { makeAuthFetch, mockResponse, renderWithApp } from "../../../test-utils/renderWithApp";
import PlatformStatusPanel from "../PlatformStatusPanel";

const checked = new Date().toISOString();
const ready = {schema_version:1, component:"vardrmap-api", status:"ready", checked_at:checked, checks:{database:"ok", migrations:"current"}};
const report = {schema_version:1, checked_at:checked, stale_after_seconds:300, runners:[{
  online:true, freshness:"recent", last_seen:checked, hostname:"operator-laptop", version:"0.51.0", os:"Linux", tools:{httpx:{ok:true, version:"v1.0"}},
}]};

it("shows readiness and account reports with observation times, versions and no execution controls", async () => {
  const {authFetch} = renderWithApp(<PlatformStatusPanel />, {routes:{"/ready":{body:ready}, "/runner/status":{body:report}}});
  expect(await screen.findByText("Ready")).toBeInTheDocument();
  expect(await screen.findByText("Recent report")).toBeInTheDocument();
  expect(screen.getByText(/Reported version 0.51.0/)).toBeInTheDocument();
  expect(screen.getByText(/httpx: available/)).toBeInTheDocument();
  expect(screen.getByText(/Last seen/)).toBeInTheDocument();
  expect(authFetch.mock.calls.every(([,init]) => !init?.method || init.method === "GET")).toBe(true);
});

it("shows database failure separately from unknown Runner reports", async () => {
  renderWithApp(<PlatformStatusPanel />, {routes:{
    "/ready":{ok:false, status:503, body:{...ready, status:"not_ready", checks:{database:"unavailable", migrations:"not_checked"}}},
    "/runner/status":{body:{...report, runners:[]}},
  }});
  expect(await screen.findByText("Not ready")).toBeInTheDocument();
  expect(await screen.findByText("No Runner has reported for this account.")).toBeInTheDocument();
  expect(screen.queryByText("Ready")).not.toBeInTheDocument();
});

it("replaces a prior success with unreachable on failed refresh", async () => {
  const authFetch = makeAuthFetch({"/ready":{body:ready}, "/runner/status":{body:report}});
  renderWithApp(<PlatformStatusPanel />, {overrides:{authFetch}});
  expect(await screen.findByText("Ready")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("button", {name:"Refresh status"})).toBeEnabled());
  authFetch.mockImplementation(async () => { throw new Error("private transport details"); });
  await userEvent.click(screen.getByRole("button", {name:"Refresh status"}));
  expect(await screen.findAllByText("Unreachable")).toHaveLength(2);
  expect(screen.queryByText("Ready")).not.toBeInTheDocument();
  expect(screen.queryByText("private transport details")).not.toBeInTheDocument();
});

it("makes a cached success stale while a refresh is pending", async () => {
  jest.useFakeTimers();
  const start = new Date("2026-10-26T12:00:00Z");
  jest.setSystemTime(start);
  const snapshot = {...ready, checked_at:start.toISOString()};
  let calls = 0;
  const authFetch = jest.fn(async (path: string) => {
    calls++;
    if (calls > 2) return new Promise<Response>(() => {});
    return mockResponse({body:path === "/ready" ? snapshot : {...report, checked_at:start.toISOString(), runners:[]}});
  });
  try {
    const view = renderWithApp(<PlatformStatusPanel />, {overrides:{authFetch}});
    await act(async () => { await Promise.resolve(); });
    expect(screen.getByText("Ready")).toBeInTheDocument();
    await act(async () => { jest.advanceTimersByTime(61000); });
    expect(screen.queryByText("Ready")).not.toBeInTheDocument();
    expect(screen.getAllByText("Stale")).toHaveLength(2);
    view.unmount();
  } finally { jest.useRealTimers(); }
});

it("does not turn unsupported or malformed contracts into health", async () => {
  renderWithApp(<PlatformStatusPanel />, {routes:{"/ready":{body:{...ready, schema_version:99}}, "/runner/status":{body:{online:true}}}});
  expect(await screen.findAllByText("Unknown")).toHaveLength(2);
  expect(screen.queryByText("Ready")).not.toBeInTheDocument();
});
