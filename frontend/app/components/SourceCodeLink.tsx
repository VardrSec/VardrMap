const REPOSITORY = "https://github.com/VardrSec/VardrMap";
const suppliedRevision = process.env.NEXT_PUBLIC_VARDRMAP_REVISION || "";
const revision = suppliedRevision.length === 40 && /^[0-9a-f]{40}$/i.test(suppliedRevision)
  ? suppliedRevision.toLowerCase() : null;

export default function SourceCodeLink() {
  return (
    <a href={revision ? `${REPOSITORY}/tree/${revision}` : REPOSITORY}
      target="_blank" rel="noopener noreferrer"
      title={revision ? `Source revision ${revision}` : "VardrMap source repository"}
      className="underline underline-offset-2 hover:text-muted-hover focus-visible:outline focus-visible:outline-2">
      {revision ? "Source code" : "Source repository"}
    </a>
  );
}
