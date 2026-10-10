import { TOOLS, PIPELINES } from "../jobs/mockData";

// The composer posts exactly these keys and defaults; the backend refuses any
// other key, and VardrRunner applies the same defaults when a key is absent.
// A toggle that rendered "disabled" while the runner treated it as enabled would
// queue a different job than the one the operator saw.
describe("tool catalog", () => {
  it("offers katana against recon or scope with JavaScript parsing off by default", () => {
    const katana = TOOLS.katana;
    expect(katana.sources).toEqual(["recon", "scope"]);
    expect(katana.yieldsTo).toBe("recon");
    expect(katana.config.map((c) => c.key)).toEqual(["depth", "limit", "js_crawl"]);
    expect(katana.config.find((c) => c.key === "js_crawl")).toMatchObject({ type: "toggle", default: false });
  });

  it("offers gau against scope only with subdomains on by default", () => {
    const gau = TOOLS.gau;
    expect(gau.sources).toEqual(["scope"]);
    expect(gau.yieldsTo).toBe("recon");
    expect(gau.config.map((c) => c.key)).toEqual(["subs", "providers"]);
    expect(gau.config.find((c) => c.key === "subs")).toMatchObject({ type: "toggle", default: true });
  });

  it("offers ffuf against recon or scope with a rate field", () => {
    const ffuf = TOOLS.ffuf;
    expect(ffuf.sources).toEqual(["recon", "scope"]);
    expect(ffuf.yieldsTo).toBe("recon");
    expect(ffuf.config.map((c) => c.key)).toEqual([
      "wordlist",
      "extensions",
      "match_codes",
      "rate",
    ]);
  });

  it("asks for a ffuf wordlist by name, never a path", () => {
    // The API refuses a path-shaped wordlist, so a placeholder that looked like
    // one would walk the operator into a 400.
    const wordlist = TOOLS.ffuf.config.find((c) => c.key === "wordlist");
    expect(wordlist).toMatchObject({ type: "text", placeholder: "common" });
    expect(wordlist!.placeholder).not.toMatch(/[/\\]/);
  });

  it("offers dalfox as a scan tool with parameter mining on by default", () => {
    const dalfox = TOOLS.dalfox;
    expect(dalfox.sources).toEqual(["recon", "scope"]);
    // Scan items, not recon: dalfox produces candidates to verify.
    expect(dalfox.yieldsTo).toBe("scan");
    expect(dalfox.config.map((c) => c.key)).toEqual(["limit", "worker", "delay", "mining"]);
    expect(dalfox.config.find((c) => c.key === "mining")).toMatchObject({ type: "toggle", default: true });
  });

  it("describes dalfox output as candidates rather than findings", () => {
    // Even dalfox's top tier is the scanner asserting exploitability, not a
    // confirmed finding, and the composer copy should not imply otherwise.
    expect(TOOLS.dalfox.yields).toBe("XSS candidates");
    expect(TOOLS.dalfox.blurb).toMatch(/candidate/i);
  });

  it("keys every tool by its own id", () => {
    for (const [key, tool] of Object.entries(TOOLS)) {
      expect(tool.id).toBe(key);
    }
  });
});

describe("pipelines", () => {
  it("includes a Content Discovery chain using katana and gau", () => {
    const content = PIPELINES.find((p) => p.id === "content-discovery");
    expect(content).toBeDefined();
    expect(content!.stages.map((s) => s.tool_type)).toEqual(["subfinder", "httpx", "katana", "gau"]);
    // katana crawls recon's live hosts; gau reads the wildcard scope.
    expect(content!.stages[2]).toMatchObject({ tool_type: "katana", target_source: "recon" });
    expect(content!.stages[3]).toMatchObject({ tool_type: "gau", target_source: "scope" });
  });

  it("only references tools that exist in the catalog", () => {
    for (const pipeline of PIPELINES) {
      for (const stage of pipeline.stages) {
        expect(TOOLS[stage.tool_type]).toBeDefined();
      }
    }
  });
});
