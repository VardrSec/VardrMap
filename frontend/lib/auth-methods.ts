export function authMethods(raw = process.env.VARDRMAP_AUTH_METHODS ?? "github"): string[] {
  const methods = [...new Set(raw.split(",").map(method => method.trim()))];
  if (!methods.length || methods.some(method => method !== "github" && method !== "local")) {
    throw new Error("VARDRMAP_AUTH_METHODS must contain github, local, or both");
  }
  return methods;
}
