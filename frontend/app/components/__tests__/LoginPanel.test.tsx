/**
 * @jest-environment jsdom
 * @jest-environment-options {"url":"https://map.example.test"}
 */
import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LoginPanel from "../LoginPanel";
import { signIn } from "next-auth/react";
import { isSecureApi } from "../../auth-client";

jest.mock("next-auth/react", () => ({ signIn: jest.fn() }));
jest.mock("../../auth-client", () => ({ API_URL: "https://api.example.test", isSecureApi: jest.fn(() => true) }));
const fetchMock = jest.fn();
beforeEach(() => { global.fetch = fetchMock; fetchMock.mockReset(); jest.mocked(isSecureApi).mockReturnValue(true); });

test("only configured login methods are offered", async () => {
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({ methods: ["github"] }) });
  render(<LoginPanel />);
  await userEvent.click(await screen.findByRole("button", { name: "Sign in with GitHub" }));
  expect(signIn).toHaveBeenCalledWith("github");
  expect(screen.queryByLabelText("Local password")).not.toBeInTheDocument();
});

test("local login uses cookies, clears the password and keeps failure details generic", async () => {
  const signedIn = jest.fn();
  fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ methods: ["local"] }) });
  fetchMock.mockResolvedValueOnce({ ok: false, json: async () => ({ detail: "private failure detail" }) });
  render(<LoginPanel onSignedIn={signedIn} />);
  await userEvent.type(await screen.findByLabelText("Local username"), "operator");
  await userEvent.type(screen.getByLabelText("Local password"), "fixture-password-only");
  await userEvent.click(screen.getByRole("button", { name: "Sign in locally" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Sign-in failed");
  expect(screen.getByLabelText("Local password")).toHaveValue("");
  expect(screen.queryByText("private failure detail")).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenLastCalledWith("https://api.example.test/auth/local/login", expect.objectContaining({
    credentials: "include", redirect: "error", body: JSON.stringify({ username: "operator", password: "fixture-password-only" }),
  }));
  expect(signedIn).not.toHaveBeenCalled();
  fetchMock.mockResolvedValueOnce({ ok: true });
  await userEvent.type(screen.getByLabelText("Local password"), "fixture-password-only");
  await userEvent.click(screen.getByRole("button", { name: "Sign in locally" }));
  await waitFor(() => expect(signedIn).toHaveBeenCalledTimes(1));
});

test("local credentials cannot be sent to an insecure API", async () => {
  jest.mocked(isSecureApi).mockReturnValue(false);
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({ methods: ["local"] }) });
  render(<LoginPanel />);
  expect(await screen.findByRole("button", { name: "Sign in locally" })).toBeDisabled();
  expect(screen.getByLabelText("Local password")).toBeDisabled();
  expect(screen.getByRole("alert")).toHaveTextContent("requires HTTPS");
});

test("unknown configuration offers no login form", async () => {
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({ methods: ["anonymous"] }) });
  render(<LoginPanel />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Unable to load sign-in methods");
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
