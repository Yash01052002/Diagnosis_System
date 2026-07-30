import { describe, expect, it } from "vitest";
import { passwordProblem } from "./password";

describe("passwordProblem", () => {
  it("accepts a strong password", () => {
    expect(passwordProblem("Str0ng!Passw0rd")).toBeNull();
  });

  it("rejects one that is too short", () => {
    expect(passwordProblem("Ab1!")).toMatch(/at least/);
  });

  it("names the missing character classes", () => {
    expect(passwordProblem("alllowercase1!")).toMatch(/uppercase/);
    expect(passwordProblem("ALLUPPERCASE1!")).toMatch(/lowercase/);
    expect(passwordProblem("NoDigitsHere!!")).toMatch(/digit/);
    expect(passwordProblem("NoSpecials123")).toMatch(/special/);
  });
});
