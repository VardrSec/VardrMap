/**
 * Test harness for components that consume AppContext.
 *
 * Renders a component inside a mock AppContext provider so Section components can
 * be tested in isolation from the real provider's auth bootstrap. `authFetch` is
 * a route-table-backed jest mock: map "METHOD /path" (or just "/path") to a
 * canned response and assert calls against it.
 *
 *   const { authFetch } = renderWithApp(<SettingsSection />, {
 *     routes: { "GET /auth/apikeys": { body: { keys: [] } } },
 *   });
 */
import { render } from "@testing-library/react";
import { ReactElement } from "react";

import { AppContext, AppContextValue } from "../app/context/AppContext";
import { initialState } from "../app/context/appReducer";

export type Route = { ok?: boolean; status?: number; body?: unknown };

export function mockResponse(r: Route = {}): Response {
  return {
    ok: r.ok ?? true,
    status: r.status ?? 200,
    json: async () => r.body ?? {},
  } as unknown as Response;
}

export function makeAuthFetch(routes: Record<string, Route> = {}) {
  return jest.fn(async (path: string, init: RequestInit = {}) => {
    const method = (init.method ?? "GET").toUpperCase();
    return mockResponse(routes[`${method} ${path}`] ?? routes[path] ?? {});
  });
}

type RenderOptions = {
  routes?: Record<string, Route>;
  state?: object;
  overrides?: Partial<AppContextValue>;
};

export function renderWithApp(ui: ReactElement, opts: RenderOptions = {}) {
  const authFetch = makeAuthFetch(opts.routes);
  const dispatch = jest.fn();
  const setMessage = jest.fn();

  const value = {
    state: { ...initialState, ...(opts.state ?? {}) },
    selectedEngagement: null,
    authFetch,
    dispatch,
    setMessage,
    selectEngagement: jest.fn(),
    navigate: jest.fn(),
    navigateToDashboard: jest.fn(),
    refreshSelectedEngagement: jest.fn(async () => {}),
    loadEngagements: jest.fn(async () => {}),
    deleteEngagement: jest.fn(async () => {}),
    promoteScanToFinding: jest.fn(),
    promoteToReport: jest.fn(),
    ...(opts.overrides ?? {}),
  };

  const utils = render(
    <AppContext.Provider value={value as unknown as AppContextValue}>{ui}</AppContext.Provider>,
  );
  return { ...utils, authFetch, dispatch, setMessage, value };
}
