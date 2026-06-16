import { safeMarkdownUrl } from "../safeUrl";

describe("safeMarkdownUrl", () => {
  it("allows http / https / mailto", () => {
    expect(safeMarkdownUrl("https://example.com/x")).toBe("https://example.com/x");
    expect(safeMarkdownUrl("http://example.com")).toBe("http://example.com");
    expect(safeMarkdownUrl("mailto:a@b.com")).toBe("mailto:a@b.com");
  });

  it("allows relative, anchor, and path URLs", () => {
    expect(safeMarkdownUrl("/programs/1")).toBe("/programs/1");
    expect(safeMarkdownUrl("#section")).toBe("#section");
    expect(safeMarkdownUrl("foo/bar")).toBe("foo/bar");
    expect(safeMarkdownUrl("/a:b")).toBe("/a:b"); // colon in a path segment is relative
  });

  it("drops javascript / data / vbscript / file schemes", () => {
    expect(safeMarkdownUrl("javascript:alert(1)")).toBe("");
    expect(safeMarkdownUrl("JavaScript:alert(1)")).toBe("");
    expect(safeMarkdownUrl("data:text/html,x")).toBe("");
    expect(safeMarkdownUrl("vbscript:msgbox(1)")).toBe("");
    expect(safeMarkdownUrl("file:///etc/passwd")).toBe("");
  });

  it("defeats whitespace / control-char obfuscation", () => {
    expect(safeMarkdownUrl(" javascript:alert(1)")).toBe("");
    expect(safeMarkdownUrl("java\tscript:alert(1)")).toBe("");
    expect(safeMarkdownUrl("java\nscript:alert(1)")).toBe("");
  });
});
