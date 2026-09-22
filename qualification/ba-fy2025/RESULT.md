# BA FY2025 qualification set — not yet run

## Corpus and key

`documents/BA_FY2025_10K.txt` is The Boeing Company's FY2025 Form 10-K text
extract, copied byte-for-byte on 18 September 2026 from the owner's
three-issuer corpus
(`/Users/ericguei/Documents/Co-Pilot Agents/assessment_3issuer_20260719/corpus/`).
Its digest was verified on copy:
`0446b367110afddcc0d66bc531d70324091b5bd1a96be56b7494ccdb7472f719`,
1,177,234 bytes. The owner's instruction was no EDGAR, only what is in hand.

The three `expects` rows were selected from the owner's answer key
(`ANSWER_KEY_3ISSUER.md` in the same folder, a key source and never an admitted
document) by the locators it gives: cash and cash equivalents of 10,921
(line 2117), total revenues of 89,463 (line 1971) and long-term debt of 45,637
(line 2169). Each matched text occurs once on its page. The CP-0 row lies
inside the gate's page map (page 36, within the 16 leading lines), because the
gate can cite only what it is shown.

## How it runs (§98)

The document is larger than a request can carry whole (905,758 bytes of block
text over 108 fixed-pitch pages). CP-0 is shown its page map -- the 16 leading
lines of every page -- and names the pages each consumer is handed, in the
bundle's Step I rule 5 form. Measured offline on this route with the fixture
provider: CP-0's whole request is 555,007 bytes, and CP-L10's, handed pages
13-40, is 440,709, both under the 1,048,576-byte ceiling
(`tests/test_large_documents.py`).

## Run

- Qualification-set digest: `a30533b3530ed1e609ce33df67e50b4ce5e4f80167be4efc29f398b4c24a7bba`
- Route: `LITE_CREDIT_22 / LITE_EARNINGS_UPDATE` (`CP-0`, `CP-L10`, `CP-5`)
- **Not run.** No live provider call was authorized for this set; nothing here
  is qualified.
