import { MOODYS_SCALE, SP_FITCH_SCALE } from "@/sections/book/view";

describe("Book rating scales", () => {
  it("carries the agency scales of caos/book/classification.py", () => {
    expect(MOODYS_SCALE).toHaveLength(21);
    expect(MOODYS_SCALE[0]).toBe("Aaa");
    expect(MOODYS_SCALE[20]).toBe("C");
    expect(SP_FITCH_SCALE).toHaveLength(22);
    expect(SP_FITCH_SCALE[0]).toBe("AAA");
    expect(SP_FITCH_SCALE[21]).toBe("D");
  });
});
