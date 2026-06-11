import { AppSession, FindingFormState, Program, ReportFormState, Section } from "../types";

export type AppState = {
  session: AppSession | null;
  authLoading: boolean;
  programs: Program[];
  selectedProgramId: string;
  activeSection: Section;
  message: string;
  findingPrefill: FindingFormState | null;
  reportPrefill: ReportFormState | null;
  dashboardPrefill: { tool?: string; tab?: "import" } | null;
};

export type AppAction =
  | { type: "AUTH_LOADED"; session: AppSession | null }
  | { type: "PROGRAMS_LOADED"; programs: Program[] }
  | { type: "PROGRAM_SELECT"; id: string }
  | { type: "PROGRAM_UPDATED"; program: Program }
  | { type: "PROGRAM_DELETED"; id: string }
  | { type: "NAVIGATE"; section: Section }
  | { type: "NAVIGATE_TO_DASHBOARD"; tool?: string; tab?: "import" }
  | { type: "DASHBOARD_PREFILL_CONSUMED" }
  | { type: "PROMOTE_TO_FINDING"; prefill: FindingFormState }
  | { type: "FINDING_PREFILL_CONSUMED" }
  | { type: "PROMOTE_TO_REPORT"; prefill: ReportFormState }
  | { type: "REPORT_PREFILL_CONSUMED" }
  | { type: "SET_MESSAGE"; message: string }
  | { type: "CLEAR_MESSAGE" };

export const initialState: AppState = {
  session: null,
  authLoading: true,
  programs: [],
  selectedProgramId: "",
  activeSection: "dashboard",
  message: "",
  findingPrefill: null,
  reportPrefill: null,
  dashboardPrefill: null,
};

export function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case "AUTH_LOADED":
      return { ...state, session: action.session, authLoading: false };

    case "PROGRAMS_LOADED": {
      const programs = action.programs;
      const selectedProgramId =
        state.selectedProgramId && programs.some((p) => p.id === state.selectedProgramId)
          ? state.selectedProgramId
          : programs[0]?.id ?? "";
      return { ...state, programs, selectedProgramId };
    }

    case "PROGRAM_SELECT":
      return { ...state, selectedProgramId: action.id };

    case "PROGRAM_UPDATED":
      return {
        ...state,
        programs: state.programs.some((p) => p.id === action.program.id)
          ? state.programs.map((p) => (p.id === action.program.id ? action.program : p))
          : [...state.programs, action.program],
      };

    case "PROGRAM_DELETED": {
      const remaining = state.programs.filter((p) => p.id !== action.id);
      return {
        ...state,
        programs: remaining,
        selectedProgramId: remaining[0]?.id ?? "",
        activeSection: "dashboard",
      };
    }

    case "NAVIGATE":
      return { ...state, activeSection: action.section };

    case "NAVIGATE_TO_DASHBOARD":
      return { ...state, activeSection: "dashboard", dashboardPrefill: { tool: action.tool, tab: action.tab } };

    case "DASHBOARD_PREFILL_CONSUMED":
      return { ...state, dashboardPrefill: null };

    case "PROMOTE_TO_FINDING":
      return { ...state, findingPrefill: action.prefill, activeSection: "findings" };

    case "FINDING_PREFILL_CONSUMED":
      return { ...state, findingPrefill: null };

    case "PROMOTE_TO_REPORT":
      return { ...state, reportPrefill: action.prefill, activeSection: "reports" };

    case "REPORT_PREFILL_CONSUMED":
      return { ...state, reportPrefill: null };

    case "SET_MESSAGE":
      return { ...state, message: action.message };

    case "CLEAR_MESSAGE":
      return { ...state, message: "" };

    default:
      return state;
  }
}
