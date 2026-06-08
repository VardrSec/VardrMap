import NextAuth from "next-auth";
import GitHub from "next-auth/providers/github";
import { SignJWT } from "jose";

const backendJwtSecret = new TextEncoder().encode(
  process.env.BACKEND_JWT_SECRET!
);

export const { handlers, auth, signIn, signOut } = NextAuth({
  secret: process.env.AUTH_SECRET,
  providers: [
    GitHub({
      clientId: process.env.AUTH_GITHUB_ID!,
      clientSecret: process.env.AUTH_GITHUB_SECRET!,
    }),
  ],
  session: {
    strategy: "jwt",
  },
  callbacks: {
    async jwt({ token, account, profile }) {
      if (account && profile) {
        token.githubId = String((profile as { id: string | number }).id);
        token.username =
          (profile as { login?: string }).login ??
          String(token.name ?? "");
        token.email = String(token.email ?? "");
      }

      // Regenerate the backend token on every callback so it never expires
      // mid-session. Without this the 1h token goes stale while the NextAuth
      // session (30-day default) is still valid, causing silent 401s.
      if (token.githubId) {
        token.backendToken = await new SignJWT({
          sub: String(token.githubId),
          username: String(token.username ?? ""),
          email: String(token.email ?? ""),
          iss: "vardrmap-frontend",
          aud: "vardrmap-backend",
        })
          .setProtectedHeader({ alg: "HS256" })
          .setIssuedAt()
          .setExpirationTime("1h")
          .sign(backendJwtSecret);
      }

      return token;
    },
    async session({ session, token }) {
      session.user.githubId = String(token.githubId ?? "");
      session.user.username = String(token.username ?? "");
      session.backendToken = String(token.backendToken ?? "");
      return session;
    },
  },
});