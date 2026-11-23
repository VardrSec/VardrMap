const exampleSecrets = new Set([
  "change-me-to-a-long-random-string",
  "change-me-to-a-long-random-hex-string",
]);

function rejectExample(name: string) {
  const secret = process.env[name];
  if (secret && exampleSecrets.has(secret)) {
    throw new Error(`Replace the example ${name} with a generated secret`);
  }
}

export function validateSigningSecrets() {
  rejectExample("BACKEND_JWT_SECRET");
  const primary =
    process.env.AUTH_SECRET === undefined ? "NEXTAUTH_SECRET" : "AUTH_SECRET";
  if (process.env[primary]) {
    rejectExample(primary);
  } else {
    // Auth.js uses its numbered rotation keys when the primary secret is empty.
    for (const name of ["AUTH_SECRET_1", "AUTH_SECRET_2", "AUTH_SECRET_3"]) {
      rejectExample(name);
    }
  }
}
