/** @type {import('jest').Config} */
const config = {
  preset: "ts-jest",
  // jsdom so React component tests have a DOM; the reducer unit tests are
  // environment-agnostic and pass under it unchanged.
  testEnvironment: "jsdom",
  globals: {
    "ts-jest": {
      tsconfig: "tsconfig.test.json",
    },
  },
};

module.exports = config;
