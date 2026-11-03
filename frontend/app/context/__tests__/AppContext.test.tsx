import "@testing-library/jest-dom";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { AppProvider, useAppContext } from "../AppContext";
import { getFrontendSession } from "../../auth-client";

jest.mock("../../auth-client", () => ({
  API_URL: "https://synthetic.invalid",
  getFrontendSession: jest.fn(),
  hasWorkspaceSession: (session: { backendToken?: string } | null) => Boolean(session?.backendToken),
  authenticatedOptions: (_session: unknown, init: RequestInit) => init,
}));

const fetchMock = jest.fn();
const expired = "Session expired. Please sign in again.";

function Probe() {
  const { state, setMessage } = useAppContext();
  return <><output data-testid="message">{state.message}</output><button onClick={() => setMessage("Saved.")}>Toast</button></>;
}

async function mount() {
  await act(async () => { render(<AppProvider><Probe /></AppProvider>); });
}

beforeEach(() => {
  jest.useFakeTimers();
  global.fetch = fetchMock;
  fetchMock.mockReset();
  jest.mocked(getFrontendSession).mockResolvedValue({ backendToken: "synthetic-session" });
});
afterEach(() => { jest.useRealTimers(); });

test("concurrent unauthorized bootstrap requests preserve the session-expiry notice", async () => {
  fetchMock.mockResolvedValue({ status: 401, ok: false });
  await mount();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(screen.getByTestId("message")).toHaveTextContent(expired);
});

test("session expiry remains visible after the ordinary toast timeout", async () => {
  fetchMock.mockImplementation(async (path: string) => path.endsWith("/auth/sync")
    ? { status: 401, ok: false }
    : { status: 200, ok: true, json: async () => ({ engagements: [] }) });
  await mount();
  expect(screen.getByTestId("message")).toHaveTextContent(expired);
  act(() => { jest.advanceTimersByTime(5000); });
  expect(screen.getByTestId("message")).toHaveTextContent(expired);
});

test("ordinary success toasts still clear after four seconds", async () => {
  fetchMock.mockResolvedValue({ status: 200, ok: true, json: async () => ({ engagements: [] }) });
  await mount();
  fireEvent.click(screen.getByRole("button", { name: "Toast" }));
  expect(screen.getByTestId("message")).toHaveTextContent("Saved.");
  act(() => { jest.advanceTimersByTime(4000); });
  expect(screen.getByTestId("message")).toBeEmptyDOMElement();
});

test("a network failure retains its ordinary load error", async () => {
  fetchMock.mockRejectedValue(new Error("synthetic offline"));
  await mount();
  expect(screen.getByTestId("message")).toHaveTextContent("Failed to load engagements.");
});
