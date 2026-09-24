import "@testing-library/jest-dom/vitest";
import { preloadView } from "@/app/views";
import { SECTIONS } from "@/wire/shared";

// Each section view is a lazy chunk (N65). In a browser the workspace fetches
// it beside the document; here every chunk is loaded once up front, so a
// mount resolves its view within the test's own settle rather than racing
// the module loader.
await Promise.all(SECTIONS.map(preloadView));
