import { describe, expect, it } from "vitest";
import { ApiError, errorText, toApiError } from "../api/errors";
import { formatDateTime, minutesLabel, parseDate, safeHref, splitList } from "./format";

describe("toApiError", () => {
  it("reads a plain FastAPI message", () => {
    expect(toApiError({ detail: "Incorrect email or password." }, 401).message).toBe("Incorrect email or password.");
  });

  it("turns validation errors into readable text", () => {
    const err = toApiError(
      { detail: [{ loc: ["body", "password"], msg: "Value error, Password must contain at least one letter and one number." }] },
      422,
    );
    expect(err.message).toBe("password: Password must contain at least one letter and one number.");
  });

  it("reads structured errors with a code", () => {
    const err = toApiError({ detail: { code: "consent_required", message: "Please agree first." } }, 403);
    expect(err.message).toBe("Please agree first.");
    expect(err.code).toBe("consent_required");
  });

  it("has friendly fallbacks and never leaks raw objects", () => {
    expect(toApiError(undefined, 500).message).toMatch(/our side/);
    expect(toApiError({ weird: true }, 404).message).toBe("We could not find that.");
    expect(errorText(new TypeError("Failed to fetch"))).toMatch(/Could not reach the server/);
    expect(errorText(new ApiError("Nope", 400))).toBe("Nope");
  });
});

describe("safeHref", () => {
  it("allows only http and https links", () => {
    expect(safeHref("https://meet.example.com/abc")).toBe("https://meet.example.com/abc");
    expect(safeHref("http://example.com")).toBe("http://example.com/");
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("data:text/html,<script>alert(1)</script>")).toBeNull();
    expect(safeHref("not a url")).toBeNull();
    expect(safeHref(null)).toBeNull();
  });
});

describe("formatting", () => {
  it("treats timestamps without a zone as UTC", () => {
    expect(parseDate("2026-03-01T10:00:00").toISOString()).toBe("2026-03-01T10:00:00.000Z");
    expect(parseDate("2026-03-01T10:00:00+05:30").toISOString()).toBe("2026-03-01T04:30:00.000Z");
    expect(formatDateTime(null)).toBe("—");
  });

  it("describes time limits and lists", () => {
    expect(minutesLabel(null)).toBe("No time limit");
    expect(minutesLabel(45)).toBe("45 minutes");
    expect(minutesLabel(60)).toBe("1 hour");
    expect(minutesLabel(120)).toBe("2 hours");
    expect(splitList(" Python, ,FastAPI ,")).toEqual(["Python", "FastAPI"]);
  });
});
