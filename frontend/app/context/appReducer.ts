import { AppSession, FindingFormState, ManualTestFormState, Engagement, ReportFormState, Section, SubmissionPrefill } from "../types";

export type ReviewTab = "recon" | "scans" | "manual" | "services";

export type AppState = {
  session: AppSession | null;
  authLoading: boolean;
  engagements: Engagement[];
  selectedEngagementId: string;
  activeSection: Section;
  message: string;
  findingPrefill: FindingFormState | null;
  reportPrefill: ReportFormState | null;
  submissionPrefill: SubmissionPrefill | null;
  dashboardPrefill: { tool?: string; tab?: "import" } | null;
  reviewPrefill: { tab?: ReviewTab; manualTest?: ManualTestFormState; jobId?: string; prefillEpoch?: number } | null;
};

export type AppAction =
  | { type: "AUTH_LOADED"; session: AppSession | null }
  | { type: "ENGAGEMENTS_LOADED"; engagements: Engagement[] }
  | { type: "PROGRAM_SELECT"; id: string }
  | { type: "ENGAGEMENT_UPDATED"; engagement: Engagement }
  | { type: "ENGAGEMENT_DELETED"; id: string }
  | { type: "NAVIGATE"; section: Section }
  | { type: "NAVIGATE_TO_DASHBOARD"; tool?: string; tab?: "import" }
  | { type: "DASHBOARD_PREFILL_CONSUMED" }
  | { type: "NAVIGATE_TO_REVIEW"; tab?: ReviewTab; manualTest?: ManualTestFormState; jobId?: string }
  | { type: "REVIEW_PREFILL_CONSUMED" }
  | { type: "PROMOTE_TO_FINDING"; prefill: FindingFormState }
  | { type: "FINDING_PREFILL_CONSUMED" }
  | { type: "PROMOTE_TO_REPORT"; prefill: ReportFormState }
  | { type: "REPORT_PREFILL_CONSUMED" }
  | { type: "PROMOTE_TO_SUBMISSION"; prefill: SubmissionPrefill }
  | { type: "SUBMISSION_PREFILL_CONSUMED" }
  | { type: "SET_MESSAGE"; message: string }
  | { type: "CLEAR_MESSAGE" };

export const initialState: AppState = {
  session: null,
  authLoading: true,
  engagements: [],
  selectedEngagementId: "",
  activeSection: "dashboard",
  message: "",
  findingPrefill: null,
  reportPrefill: null,
  submissionPrefill: null,
  dashboardPrefill: null,
  reviewPrefill: null,
};

export function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case "AUTH_LOADED":
      return { ...state, session: action.session, authLoading: false };

    case "ENGAGEMENTS_LOADED": {
      const engagements = action.engagements;
      const selectedEngagementId =
        state.selectedEngagementId && engagements.some((p) => p.id === state.selectedEngagementId)
          ? state.selectedEngagementId
          : engagements[0]?.id ?? "";
      return { ...state, engagements, selectedEngagementId };
    }

    case "PROGRAM_SELECT":
      return { ...state, selectedEngagementId: action.id };

    case "ENGAGEMENT_UPDATED":
      return {
        ...state,
        engagements: state.engagements.some((p) => p.id === action.engagement.id)
          ? state.engagements.map((p) => (p.id === action.engagement.id ? action.engagement : p))
          : [...state.engagements, action.engagement],
      };

    case "ENGAGEMENT_DELETED": {
      const remaining = state.engagements.filter((p) => p.id !== action.id);
      return {
        ...state,
        engagements: remaining,
        selectedEngagementId: remaining[0]?.id ?? "",
        activeSection: "dashboard",
      };
    }

    case "NAVIGATE":
      return { ...state, activeSection: action.section };

    case "NAVIGATE_TO_DASHBOARD":
      return { ...state, activeSection: "dashboard", dashboardPrefill: { tool: action.tool, tab: action.tab } };

    case "DASHBOARD_PREFILL_CONSUMED":
      return { ...state, dashboardPrefill: null };

    case "NAVIGATE_TO_REVIEW":
      return {
        ...state,
        activeSection: "review",
        reviewPrefill: {
          tab: action.tab,
          manualTest: action.manualTest,
          jobId: action.jobId,
          prefillEpoch: (state.reviewPrefill?.prefillEpoch ?? 0) + 1,
        },
      };

    case "REVIEW_PREFILL_CONSUMED":
      return { ...state, reviewPrefill: null };

    case "PROMOTE_TO_FINDING":
      return { ...state, findingPrefill: action.prefill, activeSection: "findings" };

    case "FINDING_PREFILL_CONSUMED":
      return { ...state, findingPrefill: null };

    case "PROMOTE_TO_REPORT":
      return { ...state, reportPrefill: action.prefill, activeSection: "reports" };

    case "REPORT_PREFILL_CONSUMED":
      return { ...state, reportPrefill: null };

    case "PROMOTE_TO_SUBMISSION":
      return { ...state, submissionPrefill: action.prefill, activeSection: "submissions" };

    case "SUBMISSION_PREFILL_CONSUMED":
      return { ...state, submissionPrefill: null };

    case "SET_MESSAGE":
      return { ...state, message: action.message };

    case "CLEAR_MESSAGE":
      return { ...state, message: "" };

    default:
      return state;
  }
}
