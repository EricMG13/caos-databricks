// Flat config. Three rule families, one per measured failure mode
// (docs/AI_CODE_QUALITY.md section 1): type-aware correctness, the rules of
// hooks, and the a11y basics that the axe gate would otherwise catch late.
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import jsxA11y from "eslint-plugin-jsx-a11y";

export default tseslint.config(
  {
    ignores: [
      "dist/",
      "dist-demo/",
      "node_modules/",
      "playwright-report/",
      "test-results/",
      "a11y-results/",
    ],
  },
  ...tseslint.configs.recommended,
  reactHooks.configs.flat.recommended,
  jsxA11y.flatConfigs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", ignoreRestSiblings: true },
      ],
      "@typescript-eslint/consistent-type-imports": "error",
      // A scroll region is focusable only when it actually clips (Panel): the
      // expression form is the WCAG scrollable-region-focusable fix.
      "jsx-a11y/no-noninteractive-tabindex": [
        "error",
        { tags: [], roles: ["tabpanel", "region"], allowExpressionValues: true },
      ],
      // A refused control is aria-disabled, never disabled (IA_SPEC.md 2).
      "no-restricted-syntax": [
        "error",
        {
          selector: "JSXAttribute[name.name='disabled']",
          message:
            "A refused control stays visible and focusable: use RefusedControl (IA_SPEC.md 2).",
        },
      ],
    },
  },
);
