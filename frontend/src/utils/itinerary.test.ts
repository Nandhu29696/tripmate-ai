import { describe, expect, it } from "vitest";
import { parsePlan, parseWeather } from "./itinerary";

const PLAN = `## Trip at a glance
- **Destination:** Tokyo, Japan
- **Dates:** 7 days in October
- **Travellers:** 2 adults

## Weather outlook
Mild, 15-22 °C. Pack a light rain jacket.

## Day 1 - Arrival & Asakusa
**Weather:** 🌤️ 18-22 °C, mostly sunny. Bring sunglasses.
- **Morning:** Fly in, check in near **Ueno**
- **Afternoon:** Senso-ji temple
- **Evening:** Izakaya dinner
- **Getting around:** Suica card
- **Est. cost:** ~$120 per person

## Day 2: Shibuya
**Weather:** 🌧️ 14-17 °C, showers likely.
- **Morning:** Meiji Shrine
- **Est. cost:** ~$90

## Budget summary
- **Total:** ~$2,400

## Before you go
- Carry your passport
`;

describe("parsePlan", () => {
  const plan = parsePlan(PLAN);

  it("reads the at-a-glance facts", () => {
    const glance = plan.blocks.find((b) => b.kind === "glance");
    expect(glance).toMatchObject({ kind: "glance" });
    if (glance?.kind !== "glance") throw new Error("no glance");
    expect(glance.items).toEqual([
      { label: "Destination", value: "Tokyo, Japan" },
      { label: "Dates", value: "7 days in October" },
      { label: "Travellers", value: "2 adults" },
    ]);
  });

  it("splits days, in order, with number and title", () => {
    expect(plan.days.map((d) => [d.number, d.title])).toEqual([
      [1, "Arrival & Asakusa"],
      [2, "Shibuya"],
    ]);
  });

  it("extracts the weather of each day", () => {
    expect(plan.days[0]?.weather).toEqual({ icon: "🌤️", text: "18-22 °C, mostly sunny. Bring sunglasses.", tone: "sun" });
    expect(plan.days[1]?.weather?.tone).toBe("rain");
  });

  it("keeps the labelled rows, including the cost", () => {
    const rows = plan.days[0]?.rows ?? [];
    expect(rows.map((r) => r.label)).toEqual(["Morning", "Afternoon", "Evening", "Getting around", "Est. cost"]);
    expect(rows[0]?.text).toBe("Fly in, check in near **Ueno**");
    expect(rows[4]?.text).toBe("~$120 per person");
  });

  it("groups the days into one block placed where the first day appeared", () => {
    expect(plan.blocks.map((b) => (b.kind === "markdown" ? b.title : b.kind))).toEqual([
      "glance",
      "Weather outlook",
      "days",
      "Budget summary",
      "Before you go",
    ]);
  });

  it("keeps text that does not fit the layout instead of dropping it", () => {
    const parsed = parsePlan("## Day 1 - Test\nA free-form note about the day.\n- **Morning:** Walk\n");
    expect(parsed.days[0]?.extra).toBe("A free-form note about the day.");
    expect(parsed.days[0]?.rows).toHaveLength(1);
  });

  it("finds no days in older, free-form plans (so the page falls back to plain markdown)", () => {
    expect(parsePlan("## Itinerary\n\n- Arrive\n- Eat\n").days).toEqual([]);
    expect(parsePlan("").days).toEqual([]);
  });

  it("does not treat headings inside code fences as sections", () => {
    const parsed = parsePlan("## Notes\n```\n## Day 9 - fake\n```\n");
    expect(parsed.days).toEqual([]);
  });

  it("handles a day without weather and a bold, differently punctuated heading", () => {
    const parsed = parsePlan("## **Day 3 — Kyoto**\n- **Morning:** Temples\n");
    expect(parsed.days[0]).toMatchObject({ number: 3, title: "Kyoto", weather: null });
  });
});

describe("parseWeather", () => {
  it("returns null for empty text", () => {
    expect(parseWeather("  ")).toBeNull();
  });

  it("works without an emoji", () => {
    expect(parseWeather("Heavy snow, -3 °C")).toEqual({ icon: "", text: "Heavy snow, -3 °C", tone: "snow" });
  });

  it("falls back to a neutral tone", () => {
    expect(parseWeather("🌫️ 10 °C")?.tone).toBe("cloud");
    expect(parseWeather("10 degrees")?.tone).toBe("neutral");
  });
});
