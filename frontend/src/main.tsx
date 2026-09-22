import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import "./styles/tokens.css";
import "./styles/caos.css";

const root = document.getElementById("root");
if (!root) throw new Error("no root element");
// A boundary that recovers re-renders the failing document, so a
// deterministically broken one is caught once per document served rather than
// once per mount. React's default handler writes every caught error to the
// console, and a render error may carry document-derived text, so the root
// takes the error and says nothing about it (`SectionBoundary` is what the
// reader sees instead).
createRoot(root, { onCaughtError() {} }).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
