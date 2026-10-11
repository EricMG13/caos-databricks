// The rate deck card (spec M14): the four reference rates by one to five
// years ahead, each with a base and a downside, entered as a percent and sent
// as the decimal the wire carries. The shift by two places is string work --
// a rate is money-adjacent and never passes through a float. Anyone signed in
// reads the latest deck; the server refuses a save from anyone but an ADMIN,
// and that refusal is shown as it came.
import { useEffect, useId, useState, type FormEvent } from "react";
import { saveRateDeck } from "@/app/commands";
import { OFFLINE_WORDING, UNAVAILABLE_WORDING, fetchRateDeck, fetchSection } from "@/app/transport";
import type { RateDeckStatus } from "@/app/transport";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CommandOutcome, useCommand } from "@/sections/run/controls";
import type { RateDeckRateView, RateDeckSaved, RateDeckView } from "@/wire/v1";

type Reference = RateDeckRateView["reference_rate"];
type Side = "base" | "downside";

const REFERENCES: readonly { value: Reference; label: string }[] = [
  { value: "SOFR", label: "SOFR" },
  { value: "TERM_SOFR", label: "Term SOFR" },
  { value: "EURIBOR", label: "EURIBOR" },
  { value: "SONIA", label: "SONIA" },
];
const YEARS = [1, 2, 3, 4, 5] as const;
const SIDES: readonly { side: Side; label: string }[] = [
  { side: "base", label: "Base" },
  { side: "downside", label: "Downside" },
];

/** More characters than any real rate needs; keeps the decimal inside the
    wire's 64. */
const MAX_ENTRY = 40;
const ENTRY = /^-?(\d+)(\.\d+)?$/;
const AS_OF_KEY = "as_of";
const ROWS_KEY = "rates";

/** A percent as the decimal string the wire carries ("3.80" is "0.0380"), by
    moving the point two places in the text. Null for anything that is not a
    plain number with magnitude under 100. */
export function percentToDecimal(entry: string): string | null {
  const text = entry.trim();
  const match = ENTRY.exec(text);
  if (!match || text.length > MAX_ENTRY) return null;
  const whole = match[1] ?? "0";
  const fraction = (match[2] ?? "").slice(1);
  if (whole.replace(/^0+/, "").length > 2) return null;
  const padded = whole.padStart(3, "0");
  const integer = padded.slice(0, -2).replace(/^0+(?=\d)/, "");
  const shifted = `${integer}.${padded.slice(-2)}${fraction}`;
  const zero = !/[1-9]/.test(shifted);
  return text.startsWith("-") && !zero ? `-${shifted}` : shifted;
}

/** The inverse, for showing a served rate: "0.0380" reads "3.80". */
export function decimalToPercent(rate: string): string {
  const negative = rate.startsWith("-");
  const [whole = "0", fraction = ""] = (negative ? rate.slice(1) : rate).split(".");
  const padded = fraction.padEnd(2, "0");
  const integer = `${whole}${padded.slice(0, 2)}`.replace(/^0+(?=\d)/, "");
  const rest = padded.slice(2);
  const text = rest ? `${integer}.${rest}` : integer;
  return negative && /[1-9]/.test(text) ? `-${text}` : text;
}

const keyOf = (reference: Reference, year: number, side: Side) => `${reference}:${year}:${side}`;

type Entries = Record<string, string>;

function entriesOf(deck: RateDeckView): Entries {
  const entries: Entries = {};
  for (const row of deck.rates) {
    entries[keyOf(row.reference_rate, row.year_offset, "base")] = decimalToPercent(row.base_rate);
    entries[keyOf(row.reference_rate, row.year_offset, "downside")] = decimalToPercent(
      row.downside_rate,
    );
  }
  return entries;
}

const RATE_WORDING = "Enter a number between -100 and 100, as a percent.";

/** Every cell's message at once, and the rows to send when there are none. */
function check(
  asOf: string,
  entries: Entries,
): { errors: Record<string, string>; rates: RateDeckRateView[] } {
  const errors: Record<string, string> = {};
  const rates: RateDeckRateView[] = [];
  if (asOf === "") errors[AS_OF_KEY] = "An as-of date is required.";
  for (const { value } of REFERENCES) {
    for (const year of YEARS) {
      const cells = SIDES.map(({ side }) => {
        const key = keyOf(value, year, side);
        return { key, text: (entries[key] ?? "").trim() };
      });
      const filled = cells.filter((cell) => cell.text !== "");
      if (filled.length === 0) continue;
      for (const cell of filled) {
        if (percentToDecimal(cell.text) === null) errors[cell.key] = RATE_WORDING;
      }
      for (const cell of cells) {
        if (cell.text === "" && filled.length === 1)
          errors[cell.key] = "Enter both rates, or neither.";
      }
      const [base, downside] = cells.map((cell) => percentToDecimal(cell.text));
      if (base != null && downside != null) {
        rates.push({
          reference_rate: value,
          year_offset: year,
          base_rate: base,
          downside_rate: downside,
        });
      }
    }
  }
  if (Object.keys(errors).length === 0 && rates.length === 0) {
    errors[ROWS_KEY] = "Enter at least one rate.";
  }
  return { errors, rates };
}

function Standing({ status }: { status: RateDeckStatus | null }) {
  if (status === null) return <p className="note">Reading the current deck…</p>;
  switch (status.kind) {
    case "ready":
      return status.deck ? (
        <p className="note" data-rate-deck-current>
          Current deck: as of {status.deck.as_of}, saved {status.deck.saved_at}.
        </p>
      ) : (
        <p className="note" data-rate-deck-current>
          No deck has been saved.
        </p>
      );
    case "offline":
      return (
        <p className="note crit" role="alert">
          {OFFLINE_WORDING}
        </p>
      );
    case "unavailable":
      return (
        <p className="note crit" role="alert">
          {UNAVAILABLE_WORDING}
        </p>
      );
    default:
      return (
        <p className="note crit" role="alert">
          {status.refusal.code} — clears when {status.refusal.clears}
        </p>
      );
  }
}

/** The region's state once the deck read has settled, in the vocabulary of
    `SurfaceState`; a deck on show is `ready`, the one state that component
    leaves unmarked, so the card names it itself. */
function regionState(status: RateDeckStatus | null): string {
  if (status === null) return "loading";
  if (status.kind === "ready") return status.deck ? "ready" : "observed-empty";
  return status.kind;
}

export function RateDeckCard() {
  const base = useId();
  const [status, setStatus] = useState<RateDeckStatus | null>(null);
  const [reads, setReads] = useState(0);
  const [editable, setEditable] = useState(false);
  const [asOf, setAsOf] = useState("");
  const [entries, setEntries] = useState<Entries>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const { pending, result, run } = useCommand<RateDeckSaved>();

  useEffect(() => {
    const controller = new AbortController();
    void fetchRateDeck(controller.signal).then((next) => {
      if (controller.signal.aborted) return;
      setStatus(next);
      if (next.kind === "ready" && next.deck) {
        setAsOf(next.deck.as_of);
        setEntries(entriesOf(next.deck));
      }
    });
    return () => controller.abort();
  }, [reads]);

  // The viewer's global role, from the Directory document every signed-in
  // reader can load. A UI convenience only: the server's refusal of a save
  // stays authoritative, and ServedRole enables nothing (decision 5). It fails
  // closed -- until the role is read, and if the read fails, the card is
  // read-only with no Save.
  useEffect(() => {
    const controller = new AbortController();
    void fetchSection("directory", {}, controller.signal).then((next) => {
      if (controller.signal.aborted) return;
      setEditable(
        "document" in next &&
          "served_role" in next.document.chrome &&
          next.document.chrome.served_role.global_role === "ADMIN",
      );
    });
    return () => controller.abort();
  }, []);

  const clear = (key: string) =>
    setErrors((current) => {
      if (!(key in current)) return current;
      const { [key]: _gone, ...rest } = current;
      return rest;
    });
  const messageId = (key: string) => `${base}-${key.replace(/[^A-Za-z0-9_]/g, "-")}`;
  const invalid = (key: string) =>
    errors[key] ? { "aria-invalid": true, "aria-describedby": messageId(key) } : {};
  const message = (key: string) =>
    errors[key] ? (
      <span id={messageId(key)} className="rate-err">
        {errors[key]}
      </span>
    ) : null;

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const { errors: found, rates } = check(asOf, entries);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    const request = { as_of: asOf, rates };
    const sent = await run(request, (intent) => saveRateDeck(request, intent));
    if (sent?.kind === "ok") setReads((count) => count + 1);
  };

  return (
    <section className="pnl" data-rate-deck data-surface-state={regionState(status)}>
      <header>
        <h2>Rate deck</h2>
      </header>
      <form className="pb" onSubmit={(event) => void onSubmit(event)} noValidate>
        <Standing status={status} />
        <label className="fld" htmlFor={`${base}-as-of`}>
          As of
          <Input
            id={`${base}-as-of`}
            type="date"
            value={asOf}
            onChange={(event) => {
              setAsOf(event.target.value);
              clear(AS_OF_KEY);
            }}
            readOnly={!editable}
            {...invalid(AS_OF_KEY)}
          />
        </label>
        {message(AS_OF_KEY)}
        <p className="fld-hint">
          Percent, so 3.80 is saved as 0.0380. A year left empty is left out; fill both its rates or
          neither.
        </p>
        <div className="tscroll">
          <table className="reg">
            <caption className="sr-only">Reference rates by year, in percent</caption>
            <thead>
              <tr>
                <th scope="col">Rate</th>
                <th scope="col">Year</th>
                {SIDES.map(({ side, label }) => (
                  <th scope="col" key={side}>
                    {label} (%)
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {REFERENCES.flatMap(({ value, label }) =>
                YEARS.map((year) => (
                  <tr key={`${value}:${year}`}>
                    <th scope="row">{label}</th>
                    <td>FY+{year}</td>
                    {SIDES.map(({ side }) => {
                      const key = keyOf(value, year, side);
                      return (
                        <td key={side}>
                          <Input
                            inputMode="decimal"
                            autoComplete="off"
                            aria-label={`${label} FY+${year} ${side}`}
                            value={entries[key] ?? ""}
                            onChange={(event) => {
                              setEntries((current) => ({ ...current, [key]: event.target.value }));
                              clear(key);
                            }}
                            readOnly={!editable}
                            {...invalid(key)}
                          />
                          {message(key)}
                        </td>
                      );
                    })}
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
        {message(ROWS_KEY)}
        {editable ? (
          <div className="fld">
            <Button
              type="submit"
              aria-busy={pending || undefined}
              aria-disabled={pending || undefined}
            >
              Save rate deck
            </Button>
          </div>
        ) : null}
        <CommandOutcome
          result={result}
          success={(receipt) => `Rate deck saved (${receipt.deck_id}).`}
          mark="rate-deck-saved"
        />
      </form>
    </section>
  );
}
