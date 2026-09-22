// A closed-shape DSL (brief 4.1, decision 7): one declaration yields the
// validator, the TypeScript type (`Infer`) and the JSON-Schema subset the
// contract test compares with the committed backend schema. No dependency.
//
// Validators narrow through type predicates, so no parsed JSON is ever
// asserted to a type. A refusal names the path only, never the value: the
// value may be document-derived text (CLAUDE.md "Never log document-derived
// text").

export type SchemaNode = null | boolean | number | string | SchemaNode[] | SchemaObject;
export interface SchemaObject {
  [key: string]: SchemaNode;
}

export class WireShapeError extends Error {
  readonly code = "WIRE_SHAPE_INVALID";
  readonly path: string;
  constructor(path: string) {
    super(`WIRE_SHAPE_INVALID at ${path}`);
    this.name = "WireShapeError";
    this.path = path;
  }
}

export interface Shape<T> {
  /** Returns true or throws `WireShapeError` naming the failing path. */
  readonly check: (value: unknown, path: string) => value is T;
  readonly toSchema: () => SchemaObject;
}

export type Infer<S> = S extends Shape<infer T> ? T : never;

/** Validate `value` against `shape`; the result is the value, narrowed. */
export function parse<T>(shape: Shape<T>, value: unknown, path = "$"): T {
  if (shape.check(value, path)) return value;
  throw new WireShapeError(path);
}

function refuse(path: string): never {
  throw new WireShapeError(path);
}

// Pydantic counts code points; a UTF-16 length can only over-count them.
function codePoints(text: string, max: number): number {
  if (text.length <= max) return text.length;
  let count = 0;
  for (const _ of text) count += 1;
  return count;
}

export function string(options: { max: number; pattern?: string }): Shape<string> {
  const matcher = options.pattern === undefined ? null : new RegExp(options.pattern, "u");
  return {
    check: (value, path): value is string =>
      (typeof value === "string" &&
        codePoints(value, options.max) <= options.max &&
        (matcher === null || matcher.test(value))) ||
      refuse(path),
    toSchema: () => ({
      type: "string",
      maxLength: options.max,
      ...(options.pattern === undefined ? {} : { pattern: options.pattern }),
    }),
  };
}

const UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;

export const uuid: Shape<string> = {
  check: (value, path): value is string =>
    (typeof value === "string" && UUID.test(value)) || refuse(path),
  toSchema: () => ({ type: "string", format: "uuid" }),
};

const RFC3339 =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?(Z|[+-](\d{2}):(\d{2}))$/i;

/** True for an RFC 3339 timestamp carrying an offset, with a real calendar date. */
export function isAwareDatetime(text: string): boolean {
  const match = RFC3339.exec(text);
  if (match === null) return false;
  const [year, month, day, hour, minute, second] = match.slice(1, 7).map(Number);
  const offsetHour = match[9] === undefined ? 0 : Number(match[9]);
  const offsetMinute = match[10] === undefined ? 0 : Number(match[10]);
  if ([year, month, day, hour, minute, second].some((part) => part === undefined)) return false;
  const date = new Date(Date.UTC(year!, month! - 1, day!));
  return (
    date.getUTCFullYear() === year &&
    date.getUTCMonth() === month! - 1 &&
    date.getUTCDate() === day &&
    hour! < 24 &&
    minute! < 60 &&
    second! < 60 &&
    offsetHour < 24 &&
    offsetMinute < 60
  );
}

export const datetime: Shape<string> = {
  check: (value, path): value is string =>
    (typeof value === "string" && isAwareDatetime(value)) || refuse(path),
  toSchema: () => ({ type: "string", format: "date-time" }),
};

export function int(options: { min?: number; max?: number } = {}): Shape<number> {
  return {
    check: (value, path): value is number =>
      (typeof value === "number" &&
        Number.isSafeInteger(value) &&
        (options.min === undefined || value >= options.min) &&
        (options.max === undefined || value <= options.max)) ||
      refuse(path),
    toSchema: () => ({
      type: "integer",
      ...(options.min === undefined ? {} : { minimum: options.min }),
      ...(options.max === undefined ? {} : { maximum: options.max }),
    }),
  };
}

export const number: Shape<number> = {
  check: (value, path): value is number =>
    (typeof value === "number" && Number.isFinite(value)) || refuse(path),
  toSchema: () => ({ type: "number" }),
};

export const bool: Shape<boolean> = {
  check: (value, path): value is boolean => typeof value === "boolean" || refuse(path),
  toSchema: () => ({ type: "boolean" }),
};

// A boolean literal as well as a string one: the Book's basis declares
// `accepted_only` as the constant `true`, which is a claim about what the
// section reads rather than a flag a body may vary.
export function literal<const V extends string | boolean>(expected: V): Shape<V> {
  return {
    check: (value, path): value is V => value === expected || refuse(path),
    toSchema: () => ({
      type: typeof expected === "string" ? "string" : "boolean",
      const: expected,
    }),
  };
}

export function enumOf<const V extends readonly string[]>(values: V): Shape<V[number]> {
  return {
    check: (value, path): value is V[number] =>
      values.some((allowed) => allowed === value) || refuse(path),
    toSchema: () => ({ type: "string", enum: [...values] }),
  };
}

export function nullable<T>(inner: Shape<T>): Shape<T | null> {
  return {
    check: (value, path): value is T | null => value === null || inner.check(value, path),
    toSchema: () => ({ anyOf: [inner.toSchema(), { type: "null" }] }),
  };
}

export function array<T>(item: Shape<T>, max: number): Shape<T[]> {
  return {
    check: (value, path): value is T[] =>
      (Array.isArray(value) &&
        value.length <= max &&
        value.every((entry, index) => item.check(entry, `${path}[${index}]`))) ||
      refuse(path),
    toSchema: () => ({ type: "array", items: item.toSchema(), maxItems: max }),
  };
}

type Fields = Record<string, Shape<unknown>>;
export type ObjectOf<F extends Fields> = { [K in keyof F]: Infer<F[K]> };

/** Closed: every declared key is required and no other key is accepted. */
export function object<const F extends Fields>(fields: F): Shape<ObjectOf<F>> {
  const declared = Object.keys(fields);
  return {
    check: (value, path): value is ObjectOf<F> => {
      if (typeof value !== "object" || value === null || Array.isArray(value)) refuse(path);
      const entries = new Map(Object.entries(value));
      if (entries.size !== declared.length || declared.some((key) => !entries.has(key))) {
        refuse(path);
      }
      for (const [key, shape] of Object.entries(fields)) {
        shape.check(entries.get(key), `${path}.${key}`);
      }
      return true;
    },
    toSchema: () => {
      const properties: SchemaObject = {};
      for (const [key, shape] of Object.entries(fields)) properties[key] = shape.toSchema();
      return {
        type: "object",
        properties,
        required: [...declared],
        additionalProperties: false,
      };
    },
  };
}
