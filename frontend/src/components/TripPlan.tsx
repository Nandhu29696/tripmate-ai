import { useMemo } from "react";
import { parsePlan, type DayPlan, type GlanceItem } from "../utils/itinerary";
import { Icon, type IconName } from "./Icon";
import { Markdown } from "./Markdown";

const GLANCE_ICON: [RegExp, IconName][] = [
  [/destination|where/i, "pin"],
  [/date|duration|when/i, "calendar"],
  [/travel/i, "users"],
  [/budget|cost/i, "wallet"],
  [/getting|flight|fly/i, "plane"],
  [/stay|hotel|sleep/i, "bed"],
];

const ROW_ICON: [RegExp, IconName][] = [
  [/morning/i, "sun"],
  [/afternoon/i, "compass"],
  [/evening|night|dinner/i, "moon"],
  [/getting|transport|around/i, "route"],
  [/cost|price|budget/i, "wallet"],
];

function iconFor(table: [RegExp, IconName][], label: string, fallback: IconName): IconName {
  return table.find(([pattern]) => pattern.test(label))?.[1] ?? fallback;
}

function jumpTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function Glance({ items, hideBudget }: { items: GlanceItem[]; hideBudget: boolean }) {
  // One total only: when the budget summary has it, the banner shows it and this tile would risk a different figure.
  const shown = hideBudget ? items.filter((item) => !/budget/i.test(item.label)) : items;
  return (
    <section className="glance" aria-label="Trip at a glance">
      {shown.map((item) => (
        <div key={item.label} className="glance-tile">
          <span className="glance-icon">
            <Icon name={iconFor(GLANCE_ICON, item.label, "info")} size={18} />
          </span>
          <div>
            <span className="glance-label">{item.label}</span>
            <Markdown className="prose-inline glance-value">{item.value}</Markdown>
          </div>
        </div>
      ))}
    </section>
  );
}

function BudgetBanner({ total, perPerson }: { total: string; perPerson: string }) {
  return (
    <section className="budget-banner" aria-label="Estimated total budget">
      <span className="budget-icon">
        <Icon name="wallet" size={22} />
      </span>
      <div className="budget-main">
        <span className="budget-label">Estimated total budget</span>
        <Markdown className="prose-inline budget-total">{total}</Markdown>
      </div>
      {perPerson && (
        <div className="budget-per">
          <span className="budget-label">Per person</span>
          <Markdown className="prose-inline">{perPerson}</Markdown>
        </div>
      )}
      <span className="budget-note">Approximate; check live prices before booking.</span>
    </section>
  );
}

function Day({ day }: { day: DayPlan }) {
  const costRows = day.rows.filter((row) => /cost|price/i.test(row.label));
  const mainRows = day.rows.filter((row) => !/cost|price/i.test(row.label));
  return (
    <article className="day-card" id={`day-${day.number}`} aria-label={`Day ${day.number}`}>
      <header className="day-head">
        <span className="day-badge" aria-hidden="true">
          <small>Day</small>
          {day.number}
        </span>
        <h3>{day.title || `Day ${day.number}`}</h3>
        {day.weather && (
          <span className={`weather-chip tone-${day.weather.tone}`} title="Expected weather">
            {day.weather.icon ? <span aria-hidden="true">{day.weather.icon}</span> : <Icon name="thermo" size={14} />}
            <span className="sr-only">Weather: </span>
            {day.weather.text}
          </span>
        )}
      </header>

      <ul className="day-rows">
        {mainRows.map((row) => (
          <li key={row.label}>
            <span className="row-icon">
              <Icon name={iconFor(ROW_ICON, row.label, "sparkles")} size={16} />
            </span>
            <div className="row-body">
              <span className="row-label">{row.label}</span>
              <Markdown className="prose-inline">{row.text}</Markdown>
            </div>
          </li>
        ))}
      </ul>

      {day.extra && <Markdown className="day-extra">{day.extra}</Markdown>}

      {costRows.map((row) => (
        <footer key={row.label} className="day-cost">
          <Icon name="wallet" size={16} />
          <span>{row.label}</span>
          <Markdown className="prose-inline">{row.text}</Markdown>
        </footer>
      ))}
    </article>
  );
}

/**
 * The plan, laid out day by day. Falls back to plain markdown for older trips or
 * answers that do not follow the layout (nothing is hidden when parsing finds no days).
 */
export function TripPlan({ markdown }: { markdown: string }) {
  const plan = useMemo(() => parsePlan(markdown), [markdown]);

  if (plan.days.length === 0) return <Markdown>{markdown}</Markdown>;

  return (
    <div className="trip-plan">
      {plan.days.length > 1 && (
        <nav className="day-jump no-print" aria-label="Jump to a day">
          {plan.days.map((day) => (
            <button key={day.number} type="button" className="chip" onClick={() => jumpTo(`day-${day.number}`)}>
              Day {day.number}
            </button>
          ))}
        </nav>
      )}

      {plan.blocks.map((block, index) => {
        if (block.kind === "glance") {
          return (
            <div key={index}>
              <Glance items={block.items} hideBudget={Boolean(plan.budget?.fromSummary)} />
              {plan.budget && <BudgetBanner total={plan.budget.total} perPerson={plan.budget.perPerson} />}
              {block.rest && <Markdown>{block.rest}</Markdown>}
            </div>
          );
        }
        if (block.kind === "days") {
          return (
            <div key={index} className="days">
              <h3 className="plan-section-title">
                <Icon name="calendar" size={18} /> Day by day
              </h3>
              <div className="day-list">
                {block.days.map((day) => (
                  <Day key={day.number} day={day} />
                ))}
              </div>
            </div>
          );
        }
        return (
          <section key={index} className={`plan-section${/weather/i.test(block.title) ? " is-weather" : ""}`}>
            {block.title && (
              <h3 className="plan-section-title">
                <Icon name={/weather/i.test(block.title) ? "cloud" : /budget/i.test(block.title) ? "wallet" : /flight/i.test(block.title) ? "plane" : /hotel/i.test(block.title) ? "bed" : "info"} size={18} />{" "}
                {block.title}
              </h3>
            )}
            <Markdown>{block.body}</Markdown>
          </section>
        );
      })}
    </div>
  );
}
