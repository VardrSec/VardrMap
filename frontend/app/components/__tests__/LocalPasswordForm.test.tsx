import "@testing-library/jest-dom";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithApp } from "../../../test-utils/renderWithApp";
import LocalPasswordForm from "../LocalPasswordForm";

async function fill(confirm = "replacement-fixture-passphrase") {
  await userEvent.type(screen.getByLabelText("Current password"), "current-fixture-passphrase");
  await userEvent.type(screen.getByLabelText("New password", { exact: true }), "replacement-fixture-passphrase");
  await userEvent.type(screen.getByLabelText("Confirm new password"), confirm);
  await userEvent.click(screen.getByRole("button", { name: "Change password" }));
}

test("confirmation mismatch never sends credentials", async () => {
  const { authFetch } = renderWithApp(<LocalPasswordForm />);
  await fill("different-fixture-passphrase");
  expect(screen.getByRole("alert")).toHaveTextContent("do not match");
  expect(authFetch).not.toHaveBeenCalled();
});

test("password change refreshes session metadata and clears inputs", async () => {
  const changed = jest.fn();
  const { authFetch } = renderWithApp(<LocalPasswordForm onChanged={changed} />, {
    routes: { "POST /auth/local/password": { body: { changed: true } } },
  });
  await fill();
  await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
  expect(authFetch).toHaveBeenCalledWith("/auth/local/password", { method: "POST", body: JSON.stringify({ current_password: "current-fixture-passphrase", new_password: "replacement-fixture-passphrase" }) });
  expect(screen.getByLabelText("Current password")).toHaveValue("");
  expect(screen.getByLabelText("New password", { exact: true })).toHaveValue("");
});
