// A saved artifact's two texts (D60): its Markdown, formatted by default and
// exactly as written one tab away, and its record. The formatted view is
// `render.py`'s element set drawn as React elements; the written one and the
// record are the signed bytes a digest binds, each in a keyboard-scrollable
// region. The tabs are the page's own views, built by the host; nothing in
// them comes from the artifact.
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { scrollArtifact } from "@/controls/scroll";
import { Markdown } from "@/ds/ModelMarkdown";

/* Keyboard scroll makes static, wide canonical text reachable in every browser. */
/* eslint-disable jsx-a11y/no-noninteractive-element-interactions */
function Exact({ text, label, mark }: { text: string; label: string; mark: string }) {
  return (
    <pre
      className="tscroll artifact-scroll"
      {...{ [mark]: true }}
      aria-label={label}
      role="region"
      tabIndex={0} // NOSONAR typescript:S6845 -- role="region" above makes this
      // element a keyboard-scrollable landmark (WCAG 2.1.1), not the
      // plain-<pre>-with-tabIndex the rule exists to catch.
      onKeyDown={scrollArtifact}
    >
      {text}
    </pre>
  );
}
/* eslint-enable jsx-a11y/no-noninteractive-element-interactions */

export function ArtifactTexts({
  markdown,
  record,
  label,
  section,
}: {
  markdown: string;
  record: string;
  /** Names the regions: "rn-cp-1 saved artifact". */
  label: string;
  /** Which section's markers the texts carry. */
  section: "report" | "committee";
}) {
  return (
    <>
      <Tabs defaultValue="formatted" className="artifact-md" data-artifact-view>
        <TabsList aria-label={`${label}: view`}>
          <TabsTrigger value="formatted" data-artifact-view-tab="formatted">
            Formatted
          </TabsTrigger>
          <TabsTrigger value="written" data-artifact-view-tab="written">
            As written
          </TabsTrigger>
        </TabsList>
        <TabsContent value="formatted" data-artifact-formatted>
          <Markdown text={markdown} base={2} label={label} />
        </TabsContent>
        <TabsContent value="written">
          <Exact
            text={markdown}
            label={`${label} markdown`}
            mark={`data-${section}-artifact-text`}
          />
        </TabsContent>
      </Tabs>
      <Exact text={record} label={`${label} record`} mark={`data-${section}-artifact-record`} />
    </>
  );
}
