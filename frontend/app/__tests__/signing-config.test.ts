/** @jest-environment node */
import { randomBytes } from "node:crypto";
import { spawnSync } from "node:child_process";
import { validateSigningSecrets } from "../../lib/signing-config";

const examples = [
  "change-me-to-a-long-random-string",
  "change-me-to-a-long-random-hex-string",
];
const settings = [
  "BACKEND_JWT_SECRET", "AUTH_SECRET", "NEXTAUTH_SECRET",
  "AUTH_SECRET_1", "AUTH_SECRET_2", "AUTH_SECRET_3",
];
const environment = process.env;

beforeEach(() => {
  process.env = { ...environment };
  for (const name of settings) delete process.env[name];
});

afterEach(() => { process.env = environment; });

it.each(settings)("rejects either example in the effective %s", (name) => {
  for (const example of examples) {
    process.env[name] = example;
    expect(validateSigningSecrets).toThrow(
      new Error(`Replace the example ${name} with a generated secret`)
    );
  }
});

it("accepts generated keys and ignores shadowed Auth.js settings", () => {
  process.env.BACKEND_JWT_SECRET = randomBytes(32).toString("hex");
  process.env.AUTH_SECRET = randomBytes(32).toString("hex");
  process.env.NEXTAUTH_SECRET = examples[0];
  process.env.AUTH_SECRET_3 = examples[1];
  expect(validateSigningSecrets).not.toThrow();

  delete process.env.AUTH_SECRET;
  process.env.NEXTAUTH_SECRET = randomBytes(32).toString("hex");
  expect(validateSigningSecrets).not.toThrow();
});

it("checks rotation keys when an empty primary shadows the legacy alias", () => {
  process.env.AUTH_SECRET = "";
  process.env.NEXTAUTH_SECRET = examples[0];
  process.env.AUTH_SECRET_1 = randomBytes(32).toString("hex");
  expect(validateSigningSecrets).not.toThrow();
  process.env.AUTH_SECRET_2 = examples[1];
  expect(validateSigningSecrets).toThrow("Replace the example AUTH_SECRET_2");
});

it("allows a build environment without runtime secrets", () => {
  expect(validateSigningSecrets).not.toThrow();
});

it("stops native Next.js startup before serving with an example session key", () => {
  const result = spawnSync(
    process.execPath,
    [require.resolve("next/dist/bin/next"), "start", "--hostname", "127.0.0.1", "--port", "0"],
    { env: { ...process.env, AUTH_SECRET: examples[0] }, encoding: "utf8", timeout: 15000 }
  );
  expect(result.error).toBeUndefined();
  expect(result.status).toBe(1);
  expect(result.stderr).toContain("Replace the example AUTH_SECRET");
  expect(result.stderr + result.stdout).not.toContain(examples[0]);
});
