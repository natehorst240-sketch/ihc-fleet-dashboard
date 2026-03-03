# Maintenance Calendar UX (Reusable)

This is a reusable React component extracted and simplified from the Figma-exported **Aircraft Maintenance Dashboard** calendar UX.

It is **framework-agnostic within React**:
- ✅ No Tailwind / Radix / shadcn required
- ✅ No icon libraries required
- ✅ Works in Vite, Next.js, CRA, Remix, etc.

## Install / copy
Copy this folder into your project, then import the component:

```tsx
import { MaintenanceCalendar, type CalendarEvent } from "./maintenance-calendar-ux";
import "./maintenance-calendar-ux/maintenance-calendar.css";

const events: CalendarEvent[] = [
  {
    id: "E1",
    aircraftId: "A1",
    registration: "N123AB",
    inspectionType: "100 Hour",
    dueDate: "2026-03-14",
    hoursRemaining: 50,
    notes: "Schedule with shop",
  },
];

export default function Page() {
  return (
    <div style={{ padding: 24 }}>
      <MaintenanceCalendar
        initialEvents={events}
        aircraft={[
          { id: "A1", registration: "N123AB" },
          { id: "A2", registration: "N456CD" },
        ]}
        inspectionTypes={[
          "Annual Inspection",
          "100 Hour",
          "200 Hour",
          "Transponder Check",
          "ELT Inspection",
          "Pitot-Static",
        ]}
        onEventsChange={(next) => console.log("events:", next)}
      />
    </div>
  );
}
```

## Props

- `initialEvents` (**required**): array of events. `dueDate` must be `YYYY-MM-DD`.
- `aircraft` (optional): list used for the Aircraft filter + Create modal.
  - If omitted, aircraft options are derived from `initialEvents`.
- `inspectionTypes` (optional): list used for the Inspection filter + Create modal.
  - If omitted, inspection options are derived from `initialEvents`.
- `initialDate` (optional): starting date (defaults to today).
- `onEventsChange` (optional): called when user creates/edits/deletes/drags events.

## UX features included
- Month / Week / Day views
- Today / previous / next navigation
- Aircraft + Inspection filters + Clear
- Create event modal
- Edit/delete event modal
- Drag & drop events (month + week)
- Hour-based urgency colors:
  - Red: <= 50
  - Amber: <= 100
  - Blue: > 100

## Notes
- This is a UI/UX component, not a full scheduling engine.
- If you want to persist changes, use `onEventsChange` to save to your backend/state store.
