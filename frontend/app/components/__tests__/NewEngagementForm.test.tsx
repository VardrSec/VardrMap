import "@testing-library/jest-dom";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderWithApp, type Route } from "../../../test-utils/renderWithApp";
import NewEngagementForm from "../NewEngagementForm";

const CLIENTS = [
  { id: "cl-1", name: "Acme Corp", contact_name: "", contact_email: "", notes: "", created_at: "" },
];

const ROUTES: Record<string, Route> = {
  "GET /clients": { body: CLIENTS },
  "POST /engagements": { body: { id: "eng-1" } },
};

/**
 * Renders and waits for the initial `/clients` load to settle.
 *
 * Without the wait the fetch resolves after the test body starts, and React
 * warns that the resulting state update was not wrapped in act(). Awaiting it
 * here keeps every test starting from a settled component.
 */
async function setup(routes = ROUTES) {
  const onCreated = jest.fn();
  const onMessage = jest.fn();
  const { authFetch } = renderWithApp(
    <NewEngagementForm onCreated={onCreated} onMessage={onMessage} />,
    { routes },
  );
  await waitFor(() => expect(authFetch).toHaveBeenCalledWith("/clients"));
  return { authFetch, onCreated, onMessage };
}

function postedBody(authFetch: jest.Mock) {
  const call = authFetch.mock.calls.find(
    (c: unknown[]) =>
      c[0] === "/engagements" && (c[1] as { method?: string } | undefined)?.method === "POST",
  );
  return JSON.parse((call![1] as { body: string }).body);
}

// --------------------------------------------------------------------------- #
// Payload
// --------------------------------------------------------------------------- #

it("defaults to pentest rather than inheriting the bug_bounty API default", async () => {
  const { authFetch } = await setup();
  await userEvent.type(screen.getByLabelText("Engagement name"), "Acme Q3");
  await userEvent.click(screen.getByRole("button", { name: "Create Engagement" }));

  await waitFor(() => expect(authFetch).toHaveBeenCalledWith(
    "/engagements", expect.objectContaining({ method: "POST" }),
  ));
  const body = postedBody(authFetch);
  expect(body.engagement_type).toBe("pentest");
  expect(body.name).toBe("Acme Q3");
});

it("sends the chosen type and status", async () => {
  const { authFetch } = await setup();
  await userEvent.type(screen.getByLabelText("Engagement name"), "Op Nightfall");
  await userEvent.selectOptions(screen.getByLabelText("Engagement type"), "red_team");
  await userEvent.selectOptions(screen.getByLabelText("Engagement status"), "active");
  await userEvent.click(screen.getByRole("button", { name: "Create Engagement" }));

  await waitFor(() => expect(authFetch).toHaveBeenCalledWith(
    "/engagements", expect.objectContaining({ method: "POST" }),
  ));
  const body = postedBody(authFetch);
  expect(body.engagement_type).toBe("red_team");
  expect(body.engagement_status).toBe("active");
});

it("sends client and testing window for a pentest", async () => {
  const { authFetch } = await setup();
  await userEvent.type(screen.getByLabelText("Engagement name"), "Acme Q3");
  await userEvent.selectOptions(await screen.findByLabelText("Client"), "cl-1");
  await userEvent.type(screen.getByLabelText("Start date"), "2026-09-01");
  await userEvent.type(screen.getByLabelText("End date"), "2026-09-14");
  await userEvent.click(screen.getByRole("button", { name: "Create Engagement" }));

  await waitFor(() => expect(authFetch).toHaveBeenCalledWith(
    "/engagements", expect.objectContaining({ method: "POST" }),
  ));
  const body = postedBody(authFetch);
  expect(body.client_id).toBe("cl-1");
  expect(body.starts_at).toBe("2026-09-01");
  expect(body.ends_at).toBe("2026-09-14");
});

it("omits client and window for a bug bounty engagement", async () => {
  const { authFetch } = await setup();
  await userEvent.type(screen.getByLabelText("Engagement name"), "Public programme");
  await userEvent.selectOptions(screen.getByLabelText("Engagement type"), "bug_bounty");
  await userEvent.click(screen.getByRole("button", { name: "Create Engagement" }));

  await waitFor(() => expect(authFetch).toHaveBeenCalledWith(
    "/engagements", expect.objectContaining({ method: "POST" }),
  ));
  const body = postedBody(authFetch);
  // Sending empty strings would store them as set-but-blank.
  expect(body).not.toHaveProperty("client_id");
  expect(body).not.toHaveProperty("starts_at");
  expect(body).not.toHaveProperty("ends_at");
});

// --------------------------------------------------------------------------- #
// Conditional fields
// --------------------------------------------------------------------------- #

it("shows the client picker for pentest and internal, not for bounty or red team", async () => {
  await setup();
  expect(await screen.findByLabelText("Client")).toBeInTheDocument();

  await userEvent.selectOptions(screen.getByLabelText("Engagement type"), "internal");
  expect(screen.getByLabelText("Client")).toBeInTheDocument();

  await userEvent.selectOptions(screen.getByLabelText("Engagement type"), "bug_bounty");
  expect(screen.queryByLabelText("Client")).not.toBeInTheDocument();

  await userEvent.selectOptions(screen.getByLabelText("Engagement type"), "red_team");
  expect(screen.queryByLabelText("Client")).not.toBeInTheDocument();
});

it("surfaces the authorization requirement for pentest and red team only", async () => {
  await setup();
  const notice = /requires a written authorization/i;
  expect(screen.getByText(notice)).toBeInTheDocument();

  await userEvent.selectOptions(screen.getByLabelText("Engagement type"), "red_team");
  expect(screen.getByText(notice)).toBeInTheDocument();

  await userEvent.selectOptions(screen.getByLabelText("Engagement type"), "bug_bounty");
  expect(screen.queryByText(notice)).not.toBeInTheDocument();

  await userEvent.selectOptions(screen.getByLabelText("Engagement type"), "internal");
  expect(screen.queryByText(notice)).not.toBeInTheDocument();
});

it("hides the testing window for bug bounty work", async () => {
  await setup();
  expect(screen.getByLabelText("Start date")).toBeInTheDocument();

  await userEvent.selectOptions(screen.getByLabelText("Engagement type"), "bug_bounty");
  expect(screen.queryByLabelText("Start date")).not.toBeInTheDocument();
});

it("prompts to add a client when none exist", async () => {
  await setup({ ...ROUTES, "GET /clients": { body: [] } });
  expect(await screen.findByText(/no clients yet/i)).toBeInTheDocument();
});

// --------------------------------------------------------------------------- #
// Behaviour
// --------------------------------------------------------------------------- #

it("will not submit without a name", async () => {
  const { authFetch } = await setup();
  expect(screen.getByRole("button", { name: "Create Engagement" })).toBeDisabled();
  expect(authFetch).not.toHaveBeenCalledWith(
    "/engagements", expect.objectContaining({ method: "POST" }),
  );
});

it("reminds the operator to record authorization after creating a pentest", async () => {
  const { onCreated, onMessage } = await setup();
  await userEvent.type(screen.getByLabelText("Engagement name"), "Acme Q3");
  await userEvent.click(screen.getByRole("button", { name: "Create Engagement" }));

  await waitFor(() => expect(onCreated).toHaveBeenCalledWith("eng-1"));
  expect(onMessage).toHaveBeenCalledWith(expect.stringMatching(/authorization/i));
});

it("does not mention authorization for a bug bounty engagement", async () => {
  const { onMessage } = await setup();
  await userEvent.type(screen.getByLabelText("Engagement name"), "Public programme");
  await userEvent.selectOptions(screen.getByLabelText("Engagement type"), "bug_bounty");
  await userEvent.click(screen.getByRole("button", { name: "Create Engagement" }));

  await waitFor(() => expect(onMessage).toHaveBeenCalled());
  expect(onMessage).toHaveBeenCalledWith("Engagement created.");
});

it("reports a failed create", async () => {
  const { onCreated, onMessage } = await setup({
    ...ROUTES,
    "POST /engagements": { ok: false, status: 422, body: { id: "" } },
  });
  await userEvent.type(screen.getByLabelText("Engagement name"), "Bad");
  await userEvent.click(screen.getByRole("button", { name: "Create Engagement" }));

  await waitFor(() => expect(onMessage).toHaveBeenCalledWith("Failed to create engagement."));
  expect(onCreated).not.toHaveBeenCalled();
});
