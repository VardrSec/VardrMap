import type { ScanJobUI } from "../../types";

export default function AssessmentBadge({ job }: { job: ScanJobUI }) {
  if (job.tool !== "vardrgate_api_test") return null;
  if (!job.assessment && !["done", "failed"].includes(job.status)) return null;
  const text = job.assessment?.status ?? "not recorded";
  return <span className="block text-xs text-[#f9e2af]">Assessment: {text}</span>;
}
