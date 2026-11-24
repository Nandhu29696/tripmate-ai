/**
 * Turns the planner's markdown into structured blocks so the page can show day cards,
 * a weather strip and an at-a-glance panel. The server asks the model for one exact
 * layout (see DAY_FORMAT in backend.py), but model output is never guaranteed: anything
 * that does not match is kept as plain markdown, so nothing is ever dropped.
 */

export interface GlanceItem {
  label: string;
  value: string;
}

export type WeatherTone = "sun" | "cloud" | "rain" | "snow" | "neutral";

export interface DayWeather {
  icon: string;
  text: string;
  tone: WeatherTone;
}

export interface DayRow {
  label: string;
  text: string;
}

export interface DayPlan {
  number: number;
  title: string;
  weather: DayWeather | null;
  rows: DayRow[];
  extra: string;
}

export type PlanBlock =
  | { kind: "markdown"; title: string; body: string }
  | { kind: "glance"; items: GlanceItem[]; rest: string }
  | { kind: "days"; days: DayPlan[] };

export interface PlanBudget {
  total: string;
  perPerson: string;
  /** Where the total came from; the at-a-glance tile is hidden when the summary is the source. */
  fromSummary: boolean;
}

export interface ParsedPlan {
  blocks: PlanBlock[];
  days: DayPlan[];
  /** The trip's total estimated cost, taken from the Budget summary (or the at-a-glance Budget). */
  budget: PlanBudget | null;
}

const DAY_HEADING = /^day\s*(\d+)\s*(?:[-–—:·|]\s*)?(.*)$/i;
const LABELLED = /^[-*•]\s+\*\*([^*]+?)\*\*\s*:?\s*(.*)$|^[-*•]\s+\*\*([^*]+?):\*\*\s*(.*)$/;
const WEATHER_LINE = /^(?:[-*•]\s+)?\*{0,2}weather\*{0,2}\s*:?\*{0,2}\s*:?\s*(.*)$/i;
const LEADING_EMOJI = /^(\p{Extended_Pictographic}(?:️|‍\p{Extended_Pictographic})*)\s*/u;

function toneFor(icon: string, text: string): WeatherTone {
  const hint = `${icon} ${text}`.toLowerCase();
  if (/[🌧⛈☔]|rain|shower|storm|drizzle/u.test(hint)) return "rain";
  if (/[❄☃]|snow|sleet|frost/u.test(hint)) return "snow";
  if (/[☁🌫]|cloud|overcast|fog|mist/u.test(hint)) return "cloud";
  if (/[☀🌤]|sun|clear|warm|hot|bright/u.test(hint)) return "sun";
  return "neutral";
}

export function parseWeather(raw: string): DayWeather | null {
  const text = raw.trim();
  if (!text) return null;
  const match = LEADING_EMOJI.exec(text);
  const icon = match?.[1] ?? "";
  const rest = (match ? text.slice(match[0].length) : text).trim();
  return { icon, text: rest, tone: toneFor(icon, rest) };
}

function stripMarkup(text: string): string {
  return text.replace(/[*_`]/g, "").trim();
}

function labelled(line: string): DayRow | null {
  const match = LABELLED.exec(line.trim());
  if (!match) return null;
  const label = (match[1] ?? match[3] ?? "").replace(/:$/, "").trim();
  const text = (match[2] ?? match[4] ?? "").trim();
  return label ? { label, text } : null;
}

function parseDay(number: number, title: string, lines: string[]): DayPlan {
  let weather: DayWeather | null = null;
  const rows: DayRow[] = [];
  const extra: string[] = [];

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      extra.push("");
      continue;
    }
    const weatherMatch = WEATHER_LINE.exec(trimmed);
    if (weatherMatch && !weather) {
      weather = parseWeather(weatherMatch[1] ?? "");
      continue;
    }
    const row = labelled(trimmed);
    if (row) {
      rows.push(row);
      continue;
    }
    extra.push(line);
  }

  return { number, title: stripMarkup(title), weather, rows, extra: extra.join("\n").trim() };
}

interface Section {
  heading: string;
  lines: string[];
}

function splitSections(markdown: string): Section[] {
  const sections: Section[] = [{ heading: "", lines: [] }];
  let inFence = false;
  for (const line of markdown.split(/\r?\n/)) {
    if (/^\s*```/.test(line)) inFence = !inFence;
    const heading = !inFence ? /^##\s+(.+?)\s*#*\s*$/.exec(line) : null;
    if (heading) sections.push({ heading: heading[1] ?? "", lines: [] });
    else sections[sections.length - 1]?.lines.push(line);
  }
  return sections;
}

export function parsePlan(markdown: string): ParsedPlan {
  const blocks: PlanBlock[] = [];
  const days: DayPlan[] = [];
  let total = "";
  let perPerson = "";
  let glanceBudget = "";
  let dayBlock: Extract<PlanBlock, { kind: "days" }> | null = null;

  for (const section of splitSections(markdown)) {
    const body = section.lines.join("\n").trim();
    const dayMatch = DAY_HEADING.exec(stripMarkup(section.heading));

    if (dayMatch) {
      const day = parseDay(Number(dayMatch[1]), dayMatch[2] ?? "", section.lines);
      days.push(day);
      if (!dayBlock) {
        dayBlock = { kind: "days", days: [] };
        blocks.push(dayBlock);
      }
      dayBlock.days.push(day);
      continue;
    }

    if (!section.heading) {
      if (body) blocks.push({ kind: "markdown", title: "", body });
      continue;
    }

    if (/^trip (at a glance|summary)$/i.test(stripMarkup(section.heading))) {
      const items: GlanceItem[] = [];
      const rest: string[] = [];
      for (const line of section.lines) {
        const row = labelled(line);
        if (row) items.push({ label: row.label, value: row.text });
        else rest.push(line);
      }
      glanceBudget = items.find((item) => /budget/i.test(item.label))?.value ?? "";
      if (items.length > 0) {
        blocks.push({ kind: "glance", items, rest: rest.join("\n").trim() });
        continue;
      }
    }

    if (/budget/i.test(section.heading)) {
      for (const line of section.lines) {
        const row = labelled(line);
        if (!row?.text) continue;
        if (/^total/i.test(row.label)) total = row.text;
        else if (/per\s*(person|traveller|traveler)/i.test(row.label)) perPerson = row.text;
      }
    }

    blocks.push({ kind: "markdown", title: stripMarkup(section.heading), body });
  }

  const headline = total || glanceBudget;
  return { blocks, days, budget: headline ? { total: headline, perPerson, fromSummary: Boolean(total) } : null };
}
