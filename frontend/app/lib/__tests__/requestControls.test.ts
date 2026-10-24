import { formatHeaders, parseHeaders, rateError, withRequestControls } from "../requestControls";

describe("parseHeaders", () => {
  it("parses Name: value lines, trimming and skipping blanks", () => {
    expect(parseHeaders("X-Bug-Bounty:  me \n\nX-Test: a:b")).toEqual({
      headers: { "X-Bug-Bounty": "me", "X-Test": "a:b" },
      error: null,
    });
  });

  it.each([
    ["no colon", '"no colon" must be Name: value'],
    ["Bad Name: x", 'invalid header name "Bad Name"'],
    ["X-A: 1\nx-a: 2", 'duplicate header "x-a"'],
    ["X-A: a\u0007b", 'header "X-A" has an invalid value'],
    [Array.from({ length: 21 }, (_, i) => `X-${i}: v`).join("\n"), "at most 20 headers"],
  ])("refuses %j", (text, error) => {
    expect(parseHeaders(text).error).toBe(error);
  });
});

describe("rateError", () => {
  it("accepts blank (tool default) and whole numbers in range", () => {
    expect(rateError("", null)).toBeNull();
    expect(rateError("1000", null)).toBeNull();
  });

  it("refuses out-of-range, fractional and above-ceiling rates", () => {
    expect(rateError("0", null)).toMatch(/1 to 1000/);
    expect(rateError("2.5", null)).toMatch(/whole number/);
    expect(rateError("11", 10)).toBe("rate exceeds this engagement's ceiling of 10/s");
  });
});

describe("withRequestControls", () => {
  const controls = { rate: "20", headers: "X-Bug-Bounty: me" };

  it("adds rate and headers only to the tools that accept each", () => {
    expect(withRequestControls("httpx", { limit: 5 }, controls)).toEqual({
      limit: 5, rate: 20, headers: { "X-Bug-Bounty": "me" },
    });
    expect(withRequestControls("dalfox", {}, controls)).toEqual({ headers: { "X-Bug-Bounty": "me" } });
    expect(withRequestControls("subfinder", {}, controls)).toEqual({});
  });

  it("drops stale values when the controls are cleared", () => {
    expect(withRequestControls("nuclei", { rate: 9, headers: { A: "b" } }, { rate: "", headers: "" })).toEqual({});
  });
});

describe("formatHeaders", () => {
  it("round-trips stored object and list forms", () => {
    expect(formatHeaders({ A: "1", B: "2" })).toBe("A: 1\nB: 2");
    expect(formatHeaders(["A: 1"])).toBe("A: 1");
    expect(formatHeaders(undefined)).toBe("");
  });
});
