import { appReducer, initialState, AppState } from "../appReducer";
import type { Program } from "../../types";

const makeProgram = (id: string, name = `Program ${id}`): Program => ({
  id,
  name,
  platform: "HackerOne",
  program_url: "",
  scope_summary: "",
  severity_guidance: "",
  safe_harbor_notes: "",
  scope: { in: [], out: [] },
  imports: [],
  recon_count: 0,
  scans_count: 0,
  manual_tests_count: 0,
  findings_count: 0,
  findings_by_severity: {},
  findings_by_status: {},
  reports_count: 0,
});

const p1 = makeProgram("1");
const p2 = makeProgram("2");

describe("appReducer", () => {
  describe("AUTH_LOADED", () => {
    it("stores session and clears authLoading", () => {
      const session = { github_id: "123", username: "user", jwt: "tok" };
      const state = appReducer(initialState, { type: "AUTH_LOADED", session });
      expect(state.session).toBe(session);
      expect(state.authLoading).toBe(false);
    });

    it("handles null session", () => {
      const state = appReducer(initialState, { type: "AUTH_LOADED", session: null });
      expect(state.session).toBeNull();
      expect(state.authLoading).toBe(false);
    });
  });

  describe("PROGRAMS_LOADED", () => {
    it("selects first program when none previously selected", () => {
      const state = appReducer(initialState, { type: "PROGRAMS_LOADED", programs: [p1, p2] });
      expect(state.programs).toEqual([p1, p2]);
      expect(state.selectedProgramId).toBe("1");
    });

    it("preserves selection when selected program is still in the list", () => {
      const base: AppState = { ...initialState, selectedProgramId: "2" };
      const state = appReducer(base, { type: "PROGRAMS_LOADED", programs: [p1, p2] });
      expect(state.selectedProgramId).toBe("2");
    });

    it("falls back to first when previously selected id is gone", () => {
      const base: AppState = { ...initialState, selectedProgramId: "99" };
      const state = appReducer(base, { type: "PROGRAMS_LOADED", programs: [p1, p2] });
      expect(state.selectedProgramId).toBe("1");
    });

    it("sets empty string when list is empty", () => {
      const state = appReducer(initialState, { type: "PROGRAMS_LOADED", programs: [] });
      expect(state.selectedProgramId).toBe("");
    });
  });

  describe("PROGRAM_SELECT", () => {
    it("updates selectedProgramId", () => {
      const state = appReducer(initialState, { type: "PROGRAM_SELECT", id: "42" });
      expect(state.selectedProgramId).toBe("42");
    });
  });

  describe("PROGRAM_UPDATED", () => {
    it("replaces an existing program by id", () => {
      const base: AppState = { ...initialState, programs: [p1, p2] };
      const updated = { ...p1, name: "Renamed" };
      const state = appReducer(base, { type: "PROGRAM_UPDATED", program: updated });
      expect(state.programs[0].name).toBe("Renamed");
      expect(state.programs).toHaveLength(2);
    });

    it("appends program if id not found", () => {
      const base: AppState = { ...initialState, programs: [p1] };
      const state = appReducer(base, { type: "PROGRAM_UPDATED", program: p2 });
      expect(state.programs).toHaveLength(2);
      expect(state.programs[1].id).toBe("2");
    });
  });

  describe("PROGRAM_DELETED", () => {
    it("removes the deleted program", () => {
      const base: AppState = { ...initialState, programs: [p1, p2], selectedProgramId: "1" };
      const state = appReducer(base, { type: "PROGRAM_DELETED", id: "1" });
      expect(state.programs).toEqual([p2]);
    });

    it("selects next available program after deletion", () => {
      const base: AppState = { ...initialState, programs: [p1, p2], selectedProgramId: "1" };
      const state = appReducer(base, { type: "PROGRAM_DELETED", id: "1" });
      expect(state.selectedProgramId).toBe("2");
    });

    it("clears selection when last program is deleted", () => {
      const base: AppState = { ...initialState, programs: [p1], selectedProgramId: "1" };
      const state = appReducer(base, { type: "PROGRAM_DELETED", id: "1" });
      expect(state.selectedProgramId).toBe("");
    });

    it("navigates to dashboard after deletion", () => {
      const base: AppState = { ...initialState, programs: [p1], activeSection: "findings" };
      const state = appReducer(base, { type: "PROGRAM_DELETED", id: "1" });
      expect(state.activeSection).toBe("dashboard");
    });
  });

  describe("NAVIGATE", () => {
    it("updates activeSection", () => {
      const state = appReducer(initialState, { type: "NAVIGATE", section: "findings" });
      expect(state.activeSection).toBe("findings");
    });
  });

  describe("NAVIGATE_TO_DASHBOARD", () => {
    it("sets activeSection to dashboard with tool prefill", () => {
      const state = appReducer(initialState, { type: "NAVIGATE_TO_DASHBOARD", tool: "nuclei" });
      expect(state.activeSection).toBe("dashboard");
      expect(state.dashboardPrefill?.tool).toBe("nuclei");
    });

    it("supports import tab prefill", () => {
      const state = appReducer(initialState, { type: "NAVIGATE_TO_DASHBOARD", tab: "import" });
      expect(state.dashboardPrefill?.tab).toBe("import");
    });
  });

  describe("DASHBOARD_PREFILL_CONSUMED", () => {
    it("clears dashboardPrefill", () => {
      const base: AppState = { ...initialState, dashboardPrefill: { tool: "nuclei" } };
      const state = appReducer(base, { type: "DASHBOARD_PREFILL_CONSUMED" });
      expect(state.dashboardPrefill).toBeNull();
    });
  });

  describe("NAVIGATE_TO_REVIEW", () => {
    it("sets activeSection to review", () => {
      const state = appReducer(initialState, { type: "NAVIGATE_TO_REVIEW", tab: "manual" });
      expect(state.activeSection).toBe("review");
    });

    it("stores tab and manualTest in reviewPrefill", () => {
      const manualTest = { title: "t", hypothesis: "h", payload: "p", evidence: "e", status: "new" };
      const state = appReducer(initialState, { type: "NAVIGATE_TO_REVIEW", tab: "manual", manualTest });
      expect(state.reviewPrefill?.tab).toBe("manual");
      expect(state.reviewPrefill?.manualTest).toBe(manualTest);
    });

    it("starts prefillEpoch at 1 on first dispatch", () => {
      const state = appReducer(initialState, { type: "NAVIGATE_TO_REVIEW" });
      expect(state.reviewPrefill?.prefillEpoch).toBe(1);
    });

    it("increments prefillEpoch on each dispatch", () => {
      const base: AppState = { ...initialState, reviewPrefill: { prefillEpoch: 3 } };
      const state = appReducer(base, { type: "NAVIGATE_TO_REVIEW" });
      expect(state.reviewPrefill?.prefillEpoch).toBe(4);
    });
  });

  describe("REVIEW_PREFILL_CONSUMED", () => {
    it("clears reviewPrefill", () => {
      const base: AppState = { ...initialState, reviewPrefill: { tab: "manual", prefillEpoch: 1 } };
      const state = appReducer(base, { type: "REVIEW_PREFILL_CONSUMED" });
      expect(state.reviewPrefill).toBeNull();
    });
  });

  describe("PROMOTE_TO_FINDING", () => {
    it("stores prefill and navigates to findings", () => {
      const prefill = { title: "XSS", severity: "high", asset: "example.com", status: "candidate", summary: "", steps: "", impact: "", remediation: "" };
      const state = appReducer(initialState, { type: "PROMOTE_TO_FINDING", prefill });
      expect(state.activeSection).toBe("findings");
      expect(state.findingPrefill).toBe(prefill);
    });
  });

  describe("FINDING_PREFILL_CONSUMED", () => {
    it("clears findingPrefill", () => {
      const prefill = { title: "XSS", severity: "high", asset: "", status: "candidate", summary: "", steps: "", impact: "", remediation: "" };
      const base: AppState = { ...initialState, findingPrefill: prefill };
      const state = appReducer(base, { type: "FINDING_PREFILL_CONSUMED" });
      expect(state.findingPrefill).toBeNull();
    });
  });

  describe("PROMOTE_TO_REPORT", () => {
    it("stores prefill and navigates to reports", () => {
      const prefill = { finding_id: "1", title: "Report", summary: "", steps: "", impact: "", remediation: "", cwe: "", cvss: "", status: "draft" };
      const state = appReducer(initialState, { type: "PROMOTE_TO_REPORT", prefill });
      expect(state.activeSection).toBe("reports");
      expect(state.reportPrefill).toBe(prefill);
    });
  });

  describe("REPORT_PREFILL_CONSUMED", () => {
    it("clears reportPrefill", () => {
      const prefill = { finding_id: "1", title: "", summary: "", steps: "", impact: "", remediation: "", cwe: "", cvss: "", status: "draft" };
      const base: AppState = { ...initialState, reportPrefill: prefill };
      const state = appReducer(base, { type: "REPORT_PREFILL_CONSUMED" });
      expect(state.reportPrefill).toBeNull();
    });
  });

  describe("SET_MESSAGE / CLEAR_MESSAGE", () => {
    it("SET_MESSAGE updates message", () => {
      const state = appReducer(initialState, { type: "SET_MESSAGE", message: "hello" });
      expect(state.message).toBe("hello");
    });

    it("CLEAR_MESSAGE resets message to empty string", () => {
      const base: AppState = { ...initialState, message: "error!" };
      const state = appReducer(base, { type: "CLEAR_MESSAGE" });
      expect(state.message).toBe("");
    });
  });

  it("returns same state for unknown action type", () => {
    // @ts-expect-error testing unknown action
    const state = appReducer(initialState, { type: "UNKNOWN" });
    expect(state).toBe(initialState);
  });
});
