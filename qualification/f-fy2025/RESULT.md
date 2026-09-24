# F FY2025 qualification set — not yet run

## Corpus and key

`documents/F_FY2025_10K.txt` is Ford Motor Company's FY2025 Form 10-K text
extract, copied byte-for-byte on 18 September 2026 from the owner's
three-issuer corpus
(`/Users/ericguei/Documents/Co-Pilot Agents/assessment_3issuer_20260719/corpus/`).
Its digest was verified on copy:
`97a38bc17e505cd1c000aa833d55e4dcfdbaedc5a75ce03a39474b9467fe4b43`,
1,922,743 bytes. The owner's instruction was no EDGAR, only what is in hand.

The three `expects` rows were selected from the owner's answer key
(`ANSWER_KEY_3ISSUER.md`, a key source and never an admitted document) by the
locators it gives: total consolidated operating cash flow of 21,282
(line 4804), Company-excluding-Ford-Credit operating cash flow of 8,351
(line 3404) and Ford Credit debt of 141,417 (line 7631) -- the perimeter
distinction the key's first trap is about. Each matched text occurs once on its
page. The CP-0 row lies inside the gate's page map (page 81, within the 10
leading lines), because the gate can cite only what it is shown.

## How it runs (§98)

The document is larger than a request can carry whole (1,435,471 bytes of
block text over 146 fixed-pitch pages). CP-0 is shown its page map -- the 10
leading lines of every page -- and names the pages each consumer is handed, in
the bundle's Step I rule 5 form. Measured offline on this route with the
fixture provider: CP-0's whole request is 545,382 bytes, and CP-L10's, handed
pages 22-64, is 555,512, both under the 1,048,576-byte ceiling
(`tests/test_large_documents.py`).

## Run

- Qualification-set digest: `645e5829dcee868d58e4c8997014a6d9351e7245fe64727d9c01f04ba9e2206f`
- Route: `LITE_CREDIT_22 / LITE_EARNINGS_UPDATE` (`CP-0`, `CP-L10`, `CP-5`)
- **Not run.** No live provider call was authorized for this set; nothing here
  is qualified.
