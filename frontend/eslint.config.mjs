import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  {
    rules: {
      // Introduced in eslint-plugin-react-hooks@7.1.0. The codebase uses two
      // intentional patterns that this rule flags:
      //   1. useEffect(() => { void loadData(); }, [loadData]) — async
      //      data-fetching effects with a stable useCallback.
      //   2. useEffect(() => { if (x) setState(x); }, [x]) — syncing
      //      external prop/context into local form state.
      // Both are accepted React patterns; address them in a dedicated pass.
      "react-hooks/set-state-in-effect": "off",
    },
  },
]);

export default eslintConfig;
