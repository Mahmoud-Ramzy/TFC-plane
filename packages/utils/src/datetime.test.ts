/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { describe, expect, it } from "vitest";

import {
  getDate,
  renderFormattedDate,
  renderFormattedPayloadDate,
  renderFormattedPayloadDateTime,
  renderWorkItemDateTime,
} from "./datetime";

/** Asserts wall-clock components so assertions hold in any host timezone. */
const expectWallClock = (
  value: ReturnType<typeof getDate>,
  year: number,
  monthIndex: number,
  day: number,
  hours = 0,
  minutes = 0
) => {
  expect(value).toBeInstanceOf(Date);
  const parsed = value as Date;
  expect(parsed.getFullYear()).toBe(year);
  expect(parsed.getMonth()).toBe(monthIndex);
  expect(parsed.getDate()).toBe(day);
  expect(parsed.getHours()).toBe(hours);
  expect(parsed.getMinutes()).toBe(minutes);
};

describe("getDate", () => {
  it("parses date-only strings as local midnight", () => {
    expectWallClock(getDate("2026-08-24"), 2026, 7, 24);
  });

  it("preserves HH:mm from datetime strings", () => {
    expectWallClock(getDate("2026-08-24T14:30"), 2026, 7, 24, 14, 30);
    expectWallClock(getDate("2026-08-24 09:05"), 2026, 7, 24, 9, 5);
  });

  it("accepts seconds but truncates to minute precision", () => {
    expectWallClock(getDate("2026-08-24T14:30:45"), 2026, 7, 24, 14, 30);
  });

  it("falls back to date-only for invalid time portions without throwing", () => {
    expectWallClock(getDate("2026-08-24Tabc"), 2026, 7, 24);
    expectWallClock(getDate("2026-08-24T99:99"), 2026, 7, 24);
    expectWallClock(getDate("2026-08-24T9"), 2026, 7, 24);
    expectWallClock(getDate("2026-08-24T"), 2026, 7, 24);
  });

  it("keeps existing behavior for missing/invalid inputs", () => {
    expect(getDate("")).toBeUndefined();
    expect(getDate(undefined)).toBeUndefined();
    expect(getDate(null)).toBeUndefined();
    // Legacy quirk preserved verbatim: unparseable strings yield an
    // Invalid Date instance (callers guard with isValid()).
    const invalid = getDate("not-a-date") as Date;
    expect(invalid.toString()).toBe("Invalid Date");
  });

  it("passes Date instances through untouched", () => {
    const now = new Date(2026, 7, 24, 14, 30);
    expect(getDate(now)).toBe(now);
  });

  it("does not shift across timezones (wall clock preserved)", () => {
    // Local construction must keep every component exactly as written.
    const earlyMorning = getDate("2026-01-01T00:30") as Date;
    expect(
      `${earlyMorning.getFullYear()}-${earlyMorning.getMonth()}-${earlyMorning.getDate()} ` +
        `${earlyMorning.getHours()}:${earlyMorning.getMinutes()}`
    ).toBe("2026-0-1 0:30");
    const lateEvening = getDate("2026-12-31T23:59") as Date;
    expect(lateEvening.getFullYear()).toBe(2026);
    expect(lateEvening.getMonth()).toBe(11);
    expect(lateEvening.getDate()).toBe(31);
    expect(`${lateEvening.getHours()}:${lateEvening.getMinutes()}`).toBe("23:59");
  });
});

describe("renderFormattedPayloadDateTime", () => {
  it("emits YYYY-MM-DD for date-only values", () => {
    expect(renderFormattedPayloadDateTime("2026-08-24")).toBe("2026-08-24");
  });

  it("emits YYYY-MM-DDTHH:mm when a time is present", () => {
    expect(renderFormattedPayloadDateTime("2026-08-24T14:30")).toBe("2026-08-24T14:30");
    expect(renderFormattedPayloadDateTime(new Date(2026, 7, 24, 8, 5))).toBe("2026-08-24T08:05");
  });

  it("normalizes seconds away in payloads", () => {
    expect(renderFormattedPayloadDateTime("2026-08-24T14:30:45")).toBe("2026-08-24T14:30");
  });

  it("falls back to date-only payloads on invalid/missing time", () => {
    expect(renderFormattedPayloadDateTime("2026-08-24Tabc")).toBe("2026-08-24");
    expect(renderFormattedPayloadDateTime("2026-08-24T99:99")).toBe("2026-08-24");
  });

  it("returns undefined for missing/invalid dates", () => {
    expect(renderFormattedPayloadDateTime(undefined)).toBeUndefined();
    expect(renderFormattedPayloadDateTime(null)).toBeUndefined();
    expect(renderFormattedPayloadDateTime("")).toBeUndefined();
    expect(renderFormattedPayloadDateTime("not-a-date")).toBeUndefined();
  });
});

describe("backward compatibility of existing formatters", () => {
  it("renderFormattedPayloadDate keeps stripping time portions", () => {
    expect(renderFormattedPayloadDate("2026-08-24")).toBe("2026-08-24");
    expect(renderFormattedPayloadDate("2026-08-24T14:30")).toBe("2026-08-24");
  });

  it("renderFormattedDate output is unchanged for datetime inputs", () => {
    expect(renderFormattedDate("2026-08-24T14:30")).toBe("Aug 24, 2026");
  });
});

describe("renderWorkItemDateTime (Work Item Start/Due display)", () => {
  it("renders date-only values exactly as before", () => {
    expect(renderWorkItemDateTime("2026-08-24")).toBe("Aug 24, 2026");
  });

  it("appends a 12-hour time when a time exists", () => {
    expect(renderWorkItemDateTime("2026-08-24T14:30")).toBe("Aug 24, 2026, 2:30 PM");
    expect(renderWorkItemDateTime(new Date(2026, 7, 24, 9, 5))).toBe("Aug 24, 2026, 9:05 AM");
  });

  it("supports 24-hour output", () => {
    expect(renderWorkItemDateTime("2026-08-24T14:30", { timeFormat: "24-hour" })).toBe("Aug 24, 2026, 14:30");
  });

  it("treats midnight as no time (existing semantics)", () => {
    expect(renderWorkItemDateTime("2026-08-24T00:00")).toBe("Aug 24, 2026");
  });

  it("normalizes seconds away before display", () => {
    expect(renderWorkItemDateTime("2026-08-24T14:30:45")).toBe("Aug 24, 2026, 2:30 PM");
  });

  it("performs no timezone conversion (wall clock preserved)", () => {
    const rendered = renderWorkItemDateTime("2026-01-01T23:59");
    expect(rendered).toBe("Jan 01, 2026, 11:59 PM");
  });

  it("returns empty string for null/undefined/invalid inputs", () => {
    expect(renderWorkItemDateTime(null)).toBe("");
    expect(renderWorkItemDateTime(undefined)).toBe("");
    expect(renderWorkItemDateTime("")).toBe("");
    expect(renderWorkItemDateTime("not-a-date")).toBe("");
  });
});
