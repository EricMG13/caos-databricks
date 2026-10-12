// Add to Book (spec B3, B5): the Model's one governed write. The control is
// drawn only where the Model read offers `ADD_TO_BOOK` in `chrome.actions`
// (a WRITER-or-above member, a complete default view, no entry yet); the
// command rechecks all of it at commit.
//
// A dialog holds the analyst-stated classification: a sector, an industry
// group of it, a domicile, and per agency a rating on its own scale with an
// outlook that only a rating takes. The fields start from the issuer's
// displayed entry in the Book, if it has one (the previous entry), and the
// analyst changes what has moved. Nothing here derives a rating or judges one:
// the server checks each word against its own vocabularies. The press asks
// once more (`ConfirmedControl`), naming the snapshot digest the analyst
// reviewed, which the server compares before it writes (invariant 5). The
// outcome is said in the dialog; the section is read again when it closes.
import { useEffect, useId, useRef, useState } from "react";
import { addToBook } from "@/app/commands";
import { fetchSection } from "@/app/transport";
import { Button } from "@/components/ui/button";
import { ConfirmedControl } from "@/controls/ConfirmedControl";
import { Overlay } from "@/evidence/Overlay";
import { CommandOutcome, useCommand } from "@/sections/run/controls";
import type { AddToBook as AddToBookRequest, BookEntryAdded, BookEntryView } from "@/wire/v1";
import {
  AGENCIES,
  GICS_SECTORS,
  MOODYS_SCALE,
  OUTLOOKS,
  SP_FITCH_SCALE,
} from "../book/classification";

type AgencyKey = (typeof AGENCIES)[number]["key"];
interface Rated {
  rating: string;
  outlook: string;
}
interface Form {
  sector: string;
  group: string;
  domicile: string;
  agencies: Record<AgencyKey, Rated>;
}

const BLANK: Form = {
  sector: "",
  group: "",
  domicile: "",
  agencies: {
    moodys: { rating: "", outlook: "" },
    sp: { rating: "", outlook: "" },
    fitch: { rating: "", outlook: "" },
  },
};

const DOMICILE_LETTERS = 2;
const SCALES = { moodys: MOODYS_SCALE, sp_fitch: SP_FITCH_SCALE } as const;

/** The issuer's Book key, as the store derives it: upper(trim(issuer_id)). */
function issuerKey(issuerId: string): string {
  return issuerId.replace(/^ +| +$/g, "").toUpperCase();
}

/** The form an entry fills: only words this dialog offers, else blank, so a
    value it cannot show is never posted by default. */
function fromEntry(entry: BookEntryView): Form {
  const agency = (key: AgencyKey, scale: readonly string[]): Rated => {
    const rating = entry[key];
    const outlook = entry[`${key}_outlook`];
    return rating !== null && scale.includes(rating)
      ? { rating, outlook: OUTLOOKS.some(([word]) => word === outlook) ? (outlook ?? "") : "" }
      : { rating: "", outlook: "" };
  };
  const groups = GICS_SECTORS[entry.sector];
  return {
    sector: groups ? entry.sector : "",
    group:
      groups && entry.industry_group && groups.includes(entry.industry_group)
        ? entry.industry_group
        : "",
    domicile: /^[A-Z]{2}$/.test(entry.domicile) ? entry.domicile : "",
    agencies: {
      moodys: agency("moodys", MOODYS_SCALE),
      sp: agency("sp", SP_FITCH_SCALE),
      fitch: agency("fitch", SP_FITCH_SCALE),
    },
  };
}

type Previous =
  { kind: "reading" } | { kind: "none" } | { kind: "unread" } | { kind: "found"; form: Form };

/** What the dialog is not yet able to send, in the words of the refusal the
    server would answer (`REQUEST_INVALID`), or null. */
function missing(form: Form): string | null {
  if (!form.sector) return "a sector is chosen";
  if (form.domicile.length !== DOMICILE_LETTERS) return "the domicile is two letters";
  return null;
}

function options(words: readonly string[]) {
  return words.map((word) => (
    <option key={word} value={word}>
      {word}
    </option>
  ));
}

function AgencyFields({
  agency,
  value,
  onChange,
}: {
  agency: (typeof AGENCIES)[number];
  value: Rated;
  onChange: (next: Rated) => void;
}) {
  const hint = useId();
  return (
    <fieldset className="book-agency" data-agency={agency.key}>
      <legend>{agency.label}</legend>
      <label className="fld">
        {agency.label} rating
        <select
          value={value.rating}
          onChange={(event) =>
            // An outlook belongs to a rating: no rating, no outlook.
            onChange({
              rating: event.target.value,
              outlook: event.target.value ? value.outlook : "",
            })
          }
        >
          <option value="">Not rated</option>
          {options(SCALES[agency.scale])}
        </select>
      </label>
      <div>
        <label className="fld">
          {agency.label} outlook
          <select
            value={value.outlook}
            aria-disabled={value.rating === "" ? true : undefined}
            aria-describedby={value.rating === "" ? hint : undefined}
            onChange={(event) => {
              // An outlook belongs to a rating: with none, a change is ignored.
              if (value.rating !== "") onChange({ ...value, outlook: event.target.value });
            }}
          >
            <option value="">No outlook</option>
            {OUTLOOKS.map(([word, label]) => (
              <option key={word} value={word}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {value.rating === "" ? (
          <span className="fld-hint" id={hint}>
            An outlook needs a rating.
          </span>
        ) : null}
      </div>
    </fieldset>
  );
}

function ClassificationForm({
  issuerName,
  caseId,
  runId,
  digest,
  start,
  onAdded,
}: {
  issuerName: string;
  caseId: string;
  runId: string;
  digest: string;
  start: Form;
  onAdded: () => void;
}) {
  const [form, setForm] = useState<Form>(start);
  const [touched, setTouched] = useState({ sector: false, domicile: false });
  const [added, setAdded] = useState(false);
  const sectorHint = useId();
  const domicileHint = useId();
  const { pending, result, run } = useCommand<BookEntryAdded>();
  const groups = GICS_SECTORS[form.sector] ?? [];
  const lack = missing(form);
  const rated = (key: AgencyKey): [string | null, string | null] => {
    const { rating, outlook } = form.agencies[key];
    return [rating || null, rating && outlook ? outlook : null];
  };

  async function submit() {
    if (lack !== null || pending || added) return;
    const [moodys, moodysOutlook] = rated("moodys");
    const [sp, spOutlook] = rated("sp");
    const [fitch, fitchOutlook] = rated("fitch");
    const body: AddToBookRequest = {
      snapshot_sha256: digest,
      sector: form.sector,
      industry_group: form.group || null,
      domicile: form.domicile,
      moodys,
      moodys_outlook: moodysOutlook,
      sp,
      sp_outlook: spOutlook,
      fitch,
      fitch_outlook: fitchOutlook,
    };
    const outcome = await run(body, (intent) => addToBook(caseId, runId, body, intent));
    if (outcome?.kind === "ok") {
      setAdded(true);
      onAdded();
    }
  }

  const setAgency = (key: AgencyKey) => (next: Rated) =>
    setForm({ ...form, agencies: { ...form.agencies, [key]: next } });
  return (
    <div className="book-form" data-add-to-book-form>
      <div className="book-pair">
        <div>
          <label className="fld">
            Sector
            <select
              value={form.sector}
              required
              aria-invalid={touched.sector && !form.sector ? true : undefined}
              aria-describedby={touched.sector && !form.sector ? sectorHint : undefined}
              onBlur={() => setTouched({ ...touched, sector: true })}
              onChange={(event) => {
                const sector = event.target.value;
                // A group belongs to its sector: another sector clears it.
                setForm({
                  ...form,
                  sector,
                  group: GICS_SECTORS[sector]?.includes(form.group) ? form.group : "",
                });
              }}
            >
              <option value="">Choose a sector</option>
              {options(Object.keys(GICS_SECTORS))}
            </select>
          </label>
          {touched.sector && !form.sector ? (
            <span className="fld-hint" role="alert" id={sectorHint}>
              Choose a sector.
            </span>
          ) : null}
        </div>
        <label className="fld">
          Industry group
          <select
            value={form.group}
            aria-disabled={groups.length === 0 ? true : undefined}
            onChange={(event) => {
              if (groups.length > 0) setForm({ ...form, group: event.target.value });
            }}
          >
            <option value="">No industry group</option>
            {options(groups)}
          </select>
        </label>
      </div>
      <div>
        <label className="fld">
          Domicile (two-letter country code)
          <input
            type="text"
            value={form.domicile}
            maxLength={DOMICILE_LETTERS}
            autoCapitalize="characters"
            autoComplete="off"
            spellCheck={false}
            aria-invalid={
              touched.domicile && form.domicile.length !== DOMICILE_LETTERS ? true : undefined
            }
            aria-describedby={
              touched.domicile && form.domicile.length !== DOMICILE_LETTERS
                ? domicileHint
                : undefined
            }
            onBlur={() => setTouched({ ...touched, domicile: true })}
            onChange={(event) =>
              setForm({
                ...form,
                domicile: event.target.value.toUpperCase().replace(/[^A-Z]/g, ""),
              })
            }
          />
        </label>
        {touched.domicile && form.domicile.length !== DOMICILE_LETTERS ? (
          <span className="fld-hint" role="alert" id={domicileHint}>
            Two letters, for example GB.
          </span>
        ) : null}
      </div>
      {AGENCIES.map((agency) => (
        <AgencyFields
          key={agency.key}
          agency={agency}
          value={form.agencies[agency.key]}
          onChange={setAgency(agency.key)}
        />
      ))}
      {added ? null : (
        <ConfirmedControl
          action="ADD_TO_BOOK"
          refusal={lack === null ? null : { code: "REQUEST_INVALID", clears: lack }}
          busy={pending}
          step={{ act: "Add to Book", subject: issuerName, digest }}
          onConfirm={() => void submit()}
          variant="default"
          aria-label={`Add ${issuerName} to the Book`}
        >
          {pending ? "Adding…" : "Add to Book"}
        </ConfirmedControl>
      )}
      <CommandOutcome
        result={result}
        success={`${issuerName} is in the Book. Close this dialog to read the Model again.`}
        mark="add-to-book-success"
      />
    </div>
  );
}

/** What the dialog holds. Mounted fresh at each opening, it reads the Book for
    the issuer's previous entry, from the same document every viewer reads; a
    read that fails is said, and the form starts blank. */
function DialogBody({
  caseId,
  runId,
  digest,
  issuerId,
  issuerName,
  onAdded,
}: {
  caseId: string;
  runId: string;
  digest: string;
  issuerId: string;
  issuerName: string;
  onAdded: () => void;
}) {
  const [previous, setPrevious] = useState<Previous>({ kind: "reading" });
  useEffect(() => {
    const controller = new AbortController();
    void fetchSection("book", {}, controller.signal).then((status) => {
      if (controller.signal.aborted) return;
      if (!("document" in status)) {
        setPrevious({ kind: "unread" });
        return;
      }
      const body = status.document.body;
      const key = issuerKey(issuerId);
      const issuer =
        "issuers" in body ? body.issuers.find((row) => row.issuer_key === key) : undefined;
      setPrevious(issuer ? { kind: "found", form: fromEntry(issuer.displayed) } : { kind: "none" });
    });
    return () => controller.abort();
  }, [issuerId]);
  if (previous.kind === "reading") {
    return (
      <p className="note book-form" role="status">
        Reading the issuer&apos;s previous entry…
      </p>
    );
  }
  return (
    <>
      {previous.kind === "unread" ? (
        <p className="note warn book-form" role="status" data-previous-unread>
          The Book could not be read, so nothing is filled in from a previous entry.
        </p>
      ) : null}
      {previous.kind === "found" ? (
        <p className="note book-form" data-previous-entry>
          Filled in from this issuer&apos;s entry in the Book. Change what has moved.
        </p>
      ) : null}
      <ClassificationForm
        issuerName={issuerName}
        caseId={caseId}
        runId={runId}
        digest={digest}
        start={previous.kind === "found" ? previous.form : BLANK}
        onAdded={onAdded}
      />
    </>
  );
}

export function AddToBook({
  caseId,
  runId,
  digest,
  issuerId,
  issuerName,
  onAdded,
}: {
  caseId: string;
  runId: string;
  /** The Model's served `snapshot_sha256`: the figures the analyst reviewed. */
  digest: string;
  issuerId: string;
  issuerName: string;
  /** Called once the dialog closes after an entry was added. */
  onAdded: () => void;
}) {
  const [opener, setOpener] = useState<HTMLElement | null>(null);
  const [open, setOpen] = useState(false);
  const [added, setAdded] = useState(false);
  // The add can land after the dialog closed (Esc while the POST is in flight):
  // the Model is then read again at once, not at a close that already passed.
  const openRef = useRef(false);
  useEffect(() => {
    openRef.current = open;
  }, [open]);
  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        data-add-to-book
        onClick={(event) => {
          setOpener(event.currentTarget);
          setOpen(true);
        }}
      >
        Add to Book
      </Button>
      {open ? (
        <Overlay
          look="modal"
          opener={opener}
          title={`Add to Book · ${issuerName}`}
          data-add-to-book-dialog=""
          onClose={() => {
            setOpen(false);
            openRef.current = false;
            if (added) onAdded();
          }}
        >
          <DialogBody
            caseId={caseId}
            runId={runId}
            digest={digest}
            issuerId={issuerId}
            issuerName={issuerName}
            onAdded={() => (openRef.current ? setAdded(true) : onAdded())}
          />
        </Overlay>
      ) : null}
    </>
  );
}
