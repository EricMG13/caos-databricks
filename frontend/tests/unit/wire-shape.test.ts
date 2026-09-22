// The closed-shape DSL behind the v1 wire validators (brief 4.1, decision 7).
import {
  WireShapeError,
  array,
  bool,
  datetime,
  enumOf,
  int,
  isAwareDatetime,
  literal,
  nullable,
  number,
  object,
  parse,
  string,
  uuid,
} from "@/wire/v1/shape";

const CASE = "3f1c2a4e-8b7d-4c6e-9a1f-0d2e3c4b5a69";
const AT = "2026-09-14T10:00:00.123456Z";

function refuses(call: () => unknown, path: string): void {
  let caught: unknown;
  try {
    call();
  } catch (error) {
    caught = error;
  }
  expect(caught).toBeInstanceOf(WireShapeError);
  if (caught instanceof WireShapeError) {
    expect(caught.code).toBe("WIRE_SHAPE_INVALID");
    expect(caught.path).toBe(path);
  }
}

test("the shape combinators refuse by path and emit their schema", () => {
  const shape = object({
    n: int({ min: 1, max: 3 }),
    f: number,
    b: bool,
    l: literal("NONE"),
    e: enumOf(["A", "B"]),
    s: nullable(string({ max: 2, pattern: "^[a-z]+$" })),
    xs: array(uuid, 1),
    at: datetime,
  });
  const good = { n: 2, f: 1.5, b: true, l: "NONE", e: "B", s: null, xs: [CASE], at: AT };
  expect(parse(shape, good)).toBe(good);
  expect(shape.toSchema().required).toEqual(["n", "f", "b", "l", "e", "s", "xs", "at"]);
  refuses(() => parse(shape, { ...good, n: 4 }), "$.n");
  refuses(() => parse(shape, { ...good, n: 0 }), "$.n");
  refuses(() => parse(shape, { ...good, f: "1" }), "$.f");
  refuses(() => parse(shape, { ...good, b: 1 }), "$.b");
  refuses(() => parse(shape, { ...good, e: "C" }), "$.e");
  refuses(() => parse(shape, { ...good, s: "ABC" }), "$.s");
  refuses(() => parse(shape, { ...good, s: "ab1" }), "$.s");
  refuses(() => parse(shape, { ...good, xs: [CASE, CASE] }), "$.xs");
  // Code points, as pydantic counts them: two astral characters fit in two.
  expect(parse(string({ max: 2 }), "\u{1F600}\u{1F600}")).toHaveLength(4);
  expect(isAwareDatetime("2026-09-14T10:00:00+05:30")).toBe(true);
  expect(isAwareDatetime("2026-09-14T24:00:00Z")).toBe(false);
  expect(isAwareDatetime("2026-09-14 10:00:00Z")).toBe(false);
});
