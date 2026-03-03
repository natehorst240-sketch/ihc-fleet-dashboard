import React, { useMemo, useState } from "react";
import type {
  AircraftOption,
  CalendarEvent,
  MaintenanceCalendarProps,
  ViewMode,
} from "./types";

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

function toISODate(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function fromISODate(iso: string): Date {
  const [y, m, dd] = iso.split("-").map((x) => parseInt(x, 10));
  const d = new Date(y, (m || 1) - 1, dd || 1);
  d.setHours(0, 0, 0, 0);
  return d;
}

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function startOfWeek(d: Date): Date {
  const start = new Date(d);
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() - start.getDay());
  return start;
}

function addDays(d: Date, days: number): Date {
  const x = new Date(d);
  x.setDate(x.getDate() + days);
  return x;
}

function eventTone(e: CalendarEvent): "red" | "amber" | "blue" {
  if (e.hoursRemaining <= 50) return "red";
  if (e.hoursRemaining <= 100) return "amber";
  return "blue";
}

function dateLabelForRange(
  viewMode: ViewMode,
  currentDate: Date,
  locale: string
): string {
  if (viewMode === "month") {
    return currentDate.toLocaleDateString(locale, {
      month: "long",
      year: "numeric",
    });
  }
  if (viewMode === "week") {
    const start = startOfWeek(currentDate);
    const end = addDays(start, 6);
    const left = start.toLocaleDateString(locale, { month: "short", day: "numeric" });
    const right = end.toLocaleDateString(locale, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
    return `${left} – ${right}`;
  }
  return currentDate.toLocaleDateString(locale, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

function deriveAircraft(events: CalendarEvent[]): AircraftOption[] {
  const map = new Map<string, AircraftOption>();
  for (const e of events) {
    const id = e.aircraftId || "";
    const reg = e.registration || "";
    if (!id && !reg) continue;
    const key = id || reg;
    if (!map.has(key)) map.set(key, { id: id || key, registration: reg || key });
  }
  return Array.from(map.values()).sort((a, b) =>
    a.registration.localeCompare(b.registration)
  );
}

function deriveInspectionTypes(events: CalendarEvent[]): string[] {
  const set = new Set<string>();
  for (const e of events) if (e.inspectionType) set.add(e.inspectionType);
  return Array.from(set.values()).sort((a, b) => a.localeCompare(b));
}

type EditForm = { dueDate: string; notes: string };
type CreateForm = {
  aircraftId: string;
  inspectionType: string;
  dueDate: string;
  hoursRemaining: string;
  notes: string;
};

export function MaintenanceCalendar(props: MaintenanceCalendarProps) {
  const {
    initialEvents,
    initialDate,
    aircraft: aircraftProp,
    inspectionTypes: inspectionProp,
    onEventsChange,
    locale = "en-US",
    enableDragDrop = true,
  } = props;

  const [currentDate, setCurrentDate] = useState<Date>(initialDate ?? new Date());
  const [viewMode, setViewMode] = useState<ViewMode>("month");

  const [events, setEvents] = useState<CalendarEvent[]>(() => [...initialEvents]);

  const aircraft = useMemo(
    () => aircraftProp ?? deriveAircraft(events),
    [aircraftProp, events]
  );
  const inspectionTypes = useMemo(
    () => inspectionProp ?? deriveInspectionTypes(events),
    [inspectionProp, events]
  );

  const [selectedAircraft, setSelectedAircraft] = useState<string>("all");
  const [selectedInspection, setSelectedInspection] = useState<string>("all");

  const [draggedEventId, setDraggedEventId] = useState<string | null>(null);

  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [editForm, setEditForm] = useState<EditForm>({ dueDate: "", notes: "" });

  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState<CreateForm>({
    aircraftId: "",
    inspectionType: "",
    dueDate: "",
    hoursRemaining: "",
    notes: "",
  });

  const filteredEvents = useMemo(() => {
    return events.filter((e) => {
      const matchesAircraft =
        selectedAircraft === "all" || (e.aircraftId ?? "") === selectedAircraft;
      const matchesInspection =
        selectedInspection === "all" || (e.inspectionType ?? "") === selectedInspection;
      return matchesAircraft && matchesInspection;
    });
  }, [events, selectedAircraft, selectedInspection]);

  const hasActiveFilters = selectedAircraft !== "all" || selectedInspection !== "all";

  function pushEvents(next: CalendarEvent[]) {
    setEvents(next);
    onEventsChange?.(next);
  }

  function goToToday() {
    setCurrentDate(new Date());
  }

  function goToPrevious() {
    const d = new Date(currentDate);
    if (viewMode === "month") d.setMonth(d.getMonth() - 1);
    else if (viewMode === "week") d.setDate(d.getDate() - 7);
    else d.setDate(d.getDate() - 1);
    setCurrentDate(d);
  }

  function goToNext() {
    const d = new Date(currentDate);
    if (viewMode === "month") d.setMonth(d.getMonth() + 1);
    else if (viewMode === "week") d.setDate(d.getDate() + 7);
    else d.setDate(d.getDate() + 1);
    setCurrentDate(d);
  }

  function clearFilters() {
    setSelectedAircraft("all");
    setSelectedInspection("all");
  }

  function openEdit(e: CalendarEvent) {
    setSelectedEvent(e);
    setEditForm({ dueDate: e.dueDate, notes: e.notes ?? "" });
    setIsEditOpen(true);
  }

  function openCreate(dateISO: string) {
    setCreateForm({
      aircraftId: "",
      inspectionType: "",
      dueDate: dateISO,
      hoursRemaining: "",
      notes: "",
    });
    setIsCreateOpen(true);
  }

  function saveEdit() {
    if (!selectedEvent) return;
    const next = events.map((e) =>
      e.id === selectedEvent.id
        ? { ...e, dueDate: editForm.dueDate, notes: editForm.notes }
        : e
    );
    pushEvents(next);
    setIsEditOpen(false);
    setSelectedEvent(null);
  }

  function deleteEvent() {
    if (!selectedEvent) return;
    const next = events.filter((e) => e.id !== selectedEvent.id);
    pushEvents(next);
    setIsEditOpen(false);
    setSelectedEvent(null);
  }

  function saveCreate() {
    const ac = aircraft.find((a) => a.id === createForm.aircraftId);
    if (!ac || !createForm.inspectionType || !createForm.dueDate) return;

    const newEvent: CalendarEvent = {
      id: `E${Date.now()}`,
      aircraftId: ac.id,
      registration: ac.registration,
      inspectionType: createForm.inspectionType,
      dueDate: createForm.dueDate,
      hoursRemaining: parseInt(createForm.hoursRemaining, 10) || 0,
      notes: createForm.notes,
    };
    pushEvents([...events, newEvent]);
    setIsCreateOpen(false);
  }

  // ----- View model helpers -----
  const monthCells = useMemo(() => {
    if (viewMode !== "month") return [];
    const first = new Date(currentDate.getFullYear(), currentDate.getMonth(), 1);
    const gridStart = startOfWeek(first);
    const cells: Date[] = [];
    for (let i = 0; i < 42; i++) cells.push(addDays(gridStart, i));
    return cells;
  }, [currentDate, viewMode]);

  const weekDays = useMemo(() => {
    if (viewMode !== "week") return [];
    const start = startOfWeek(currentDate);
    return Array.from({ length: 7 }, (_, i) => addDays(start, i));
  }, [currentDate, viewMode]);

  const dayISO = useMemo(() => toISODate(currentDate), [currentDate]);

  // ----- Drag and drop -----
  function onDragStart(id: string) {
    if (!enableDragDrop) return;
    setDraggedEventId(id);
  }
  function onDrop(dateISO: string) {
    if (!enableDragDrop) return;
    if (!draggedEventId) return;
    const next = events.map((e) => (e.id === draggedEventId ? { ...e, dueDate: dateISO } : e));
    pushEvents(next);
    setDraggedEventId(null);
  }

  // ----- Render helpers -----
  function eventsForDate(dateISO: string): CalendarEvent[] {
    return filteredEvents
      .filter((e) => e.dueDate === dateISO)
      .sort((a, b) => a.hoursRemaining - b.hoursRemaining);
  }

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  return (
    <div className="mc">
      {/* Toolbar */}
      <div className="mc-card">
        <div className="mc-card-inner">
          <div className="mc-row">
            <div className="mc-left">
              <button className="mc-btn" onClick={goToToday} type="button">
                Today
              </button>

              <button className="mc-btn icon" onClick={goToPrevious} type="button" aria-label="Previous">
                ‹
              </button>
              <button className="mc-btn icon" onClick={goToNext} type="button" aria-label="Next">
                ›
              </button>

              <div>
                <div className="mc-title">{dateLabelForRange(viewMode, currentDate, locale)}</div>
                <div className="mc-subtle">
                  {filteredEvents.length} event{filteredEvents.length === 1 ? "" : "s"}
                  {hasActiveFilters ? " (filtered)" : ""}
                </div>
              </div>
            </div>

            <div className="mc-right">
              <div className="mc-seg" role="tablist" aria-label="View mode">
                <button
                  className={viewMode === "month" ? "active" : ""}
                  onClick={() => setViewMode("month")}
                  type="button"
                >
                  Month
                </button>
                <button
                  className={viewMode === "week" ? "active" : ""}
                  onClick={() => setViewMode("week")}
                  type="button"
                >
                  Week
                </button>
                <button
                  className={viewMode === "day" ? "active" : ""}
                  onClick={() => setViewMode("day")}
                  type="button"
                >
                  Day
                </button>
              </div>

              {hasActiveFilters && (
                <span className="mc-badge" title="Filters active">
                  Filters active
                </span>
              )}
            </div>
          </div>

          {/* Filters */}
          <div style={{ marginTop: 12 }} className="mc-row">
            <div className="mc-filters">
              <span className="mc-label">Filter by:</span>

              <select
                className="mc-select"
                value={selectedAircraft}
                onChange={(e) => setSelectedAircraft(e.target.value)}
              >
                <option value="all">All Aircraft</option>
                {aircraft.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.registration}
                  </option>
                ))}
              </select>

              <select
                className="mc-select"
                value={selectedInspection}
                onChange={(e) => setSelectedInspection(e.target.value)}
              >
                <option value="all">All Inspections</option>
                {inspectionTypes.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>

              {hasActiveFilters && (
                <button className="mc-btn" onClick={clearFilters} type="button">
                  Clear
                </button>
              )}
            </div>

            <button
              className="mc-btn primary"
              onClick={() => openCreate(toISODate(currentDate))}
              type="button"
            >
              + New event
            </button>
          </div>
        </div>
      </div>

      {/* Body */}
      <div style={{ marginTop: 14 }}>
        {viewMode === "month" && (
          <div className="mc-card">
            <div className="mc-card-inner">
              <div className="mc-grid">
                <div className="mc-weekdays">
                  {WEEKDAYS.map((d) => (
                    <div key={d} className="mc-weekday">
                      {d}
                    </div>
                  ))}
                </div>

                <div className="mc-month">
                  {monthCells.map((d) => {
                    const iso = toISODate(d);
                    const list = eventsForDate(iso);
                    const inMonth = d.getMonth() === currentDate.getMonth();
                    const isToday = sameDay(d, today);

                    return (
                      <div
                        key={iso}
                        className={"mc-day" + (inMonth ? "" : " other-month")}
                        onDragOver={(e) => enableDragDrop && e.preventDefault()}
                        onDrop={() => onDrop(iso)}
                      >
                        <div className="mc-day-header">
                          <div className={"mc-daynum" + (isToday ? " today" : "")}>
                            {d.getDate()}
                          </div>
                          <button className="mc-plus" type="button" onClick={() => openCreate(iso)}>
                            +
                          </button>
                        </div>

                        {list.slice(0, 3).map((e) => (
                          <div
                            key={e.id}
                            className={`mc-event ${eventTone(e)}`}
                            draggable={enableDragDrop}
                            onDragStart={() => onDragStart(e.id)}
                            onClick={() => openEdit(e)}
                            title="Click to edit. Drag to reschedule."
                          >
                            <small>{e.registration ?? e.aircraftId ?? "Aircraft"}</small>
                            <div className="mc-event-sub">
                              {e.inspectionType ?? "Maintenance"} • {e.hoursRemaining} hrs
                            </div>
                          </div>
                        ))}

                        {list.length > 3 && (
                          <div className="mc-more">+{list.length - 3} more</div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        )}

        {viewMode === "week" && (
          <div className="mc-week">
            {weekDays.map((d) => {
              const iso = toISODate(d);
              const list = eventsForDate(iso);
              const isToday = sameDay(d, today);
              return (
                <div
                  key={iso}
                  className="mc-week-col"
                  onDragOver={(e) => enableDragDrop && e.preventDefault()}
                  onDrop={() => onDrop(iso)}
                >
                  <div className="mc-week-head">
                    <div>
                      <div className="mc-week-day">
                        {d.toLocaleDateString(locale, { weekday: "short" })}
                        {isToday ? " • Today" : ""}
                      </div>
                      <div className="mc-week-date">
                        {d.toLocaleDateString(locale, { month: "short", day: "numeric" })}
                      </div>
                    </div>
                    <button className="mc-plus" type="button" onClick={() => openCreate(iso)}>
                      +
                    </button>
                  </div>

                  {list.map((e) => (
                    <div
                      key={e.id}
                      className={`mc-event ${eventTone(e)}`}
                      draggable={enableDragDrop}
                      onDragStart={() => onDragStart(e.id)}
                      onClick={() => openEdit(e)}
                      title="Click to edit. Drag to reschedule."
                    >
                      <small>{e.registration ?? e.aircraftId ?? "Aircraft"}</small>
                      <div className="mc-event-sub">
                        {e.inspectionType ?? "Maintenance"} • {e.hoursRemaining} hrs
                      </div>
                    </div>
                  ))}

                  {list.length === 0 && (
                    <div className="mc-subtle" style={{ marginTop: 6 }}>
                      No events
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {viewMode === "day" && (
          <div className="mc-dayview">
            <div className="mc-dayview-head">
              <div>
                <h3 className="mc-dayview-title">
                  {currentDate.toLocaleDateString(locale, {
                    weekday: "long",
                    month: "long",
                    day: "numeric",
                    year: "numeric",
                  })}
                </h3>
                <div className="mc-subtle">
                  {eventsForDate(dayISO).length} event{eventsForDate(dayISO).length === 1 ? "" : "s"} scheduled
                </div>
              </div>
              <button className="mc-btn primary" onClick={() => openCreate(dayISO)} type="button">
                + Create New Event
              </button>
            </div>

            <div style={{ display: "grid", gap: 10 }}>
              {eventsForDate(dayISO).map((e) => (
                <div key={e.id} className="mc-eventcard" onClick={() => openEdit(e)}>
                  <div>
                    <div style={{ fontWeight: 900, marginBottom: 4 }}>
                      {(e.registration ?? e.aircraftId ?? "Aircraft") + " — " + (e.inspectionType ?? "Maintenance")}
                    </div>
                    {e.notes ? <div className="mc-subtle">{e.notes}</div> : <div className="mc-subtle">No notes</div>}
                  </div>
                  <span className={`mc-pill ${eventTone(e)}`}>{e.hoursRemaining} hrs</span>
                </div>
              ))}

              {eventsForDate(dayISO).length === 0 && (
                <div className="mc-subtle">No maintenance events scheduled for this day.</div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Edit modal */}
      {isEditOpen && selectedEvent && (
        <Modal title="Edit Event" onClose={() => setIsEditOpen(false)}>
          <div className="mc-field">
            <label>Aircraft</label>
            <div className="mc-subtle" style={{ fontWeight: 900 }}>
              {selectedEvent.registration ?? selectedEvent.aircraftId ?? "—"}
            </div>
          </div>

          <div className="mc-field">
            <label>Inspection</label>
            <div className="mc-subtle" style={{ fontWeight: 900 }}>
              {selectedEvent.inspectionType ?? "—"}
            </div>
          </div>

          <div className="mc-field">
            <label>Due Date</label>
            <input
              className="mc-input"
              type="date"
              value={editForm.dueDate}
              onChange={(e) => setEditForm((p) => ({ ...p, dueDate: e.target.value }))}
            />
          </div>

          <div className="mc-field">
            <label>Notes</label>
            <textarea
              className="mc-textarea"
              rows={4}
              value={editForm.notes}
              onChange={(e) => setEditForm((p) => ({ ...p, notes: e.target.value }))}
            />
          </div>

          <div className="mc-modal-foot">
            <button className="mc-btn mc-danger" onClick={deleteEvent} type="button">
              Delete
            </button>
            <button className="mc-btn" onClick={() => setIsEditOpen(false)} type="button">
              Cancel
            </button>
            <button className="mc-btn primary" onClick={saveEdit} type="button">
              Save
            </button>
          </div>
        </Modal>
      )}

      {/* Create modal */}
      {isCreateOpen && (
        <Modal title="Create Event" onClose={() => setIsCreateOpen(false)}>
          <div className="mc-field">
            <label>Aircraft</label>
            <select
              className="mc-select"
              value={createForm.aircraftId}
              onChange={(e) => setCreateForm((p) => ({ ...p, aircraftId: e.target.value }))}
            >
              <option value="">Select aircraft…</option>
              {aircraft.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.registration}
                </option>
              ))}
            </select>
          </div>

          <div className="mc-field">
            <label>Inspection Type</label>
            <select
              className="mc-select"
              value={createForm.inspectionType}
              onChange={(e) => setCreateForm((p) => ({ ...p, inspectionType: e.target.value }))}
            >
              <option value="">Select inspection…</option>
              {inspectionTypes.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>

          <div className="mc-field">
            <label>Due Date</label>
            <input
              className="mc-input"
              type="date"
              value={createForm.dueDate}
              onChange={(e) => setCreateForm((p) => ({ ...p, dueDate: e.target.value }))}
            />
          </div>

          <div className="mc-field">
            <label>Hours Remaining</label>
            <input
              className="mc-input"
              inputMode="numeric"
              placeholder="e.g. 80"
              value={createForm.hoursRemaining}
              onChange={(e) => setCreateForm((p) => ({ ...p, hoursRemaining: e.target.value }))}
            />
          </div>

          <div className="mc-field">
            <label>Notes</label>
            <textarea
              className="mc-textarea"
              rows={4}
              value={createForm.notes}
              onChange={(e) => setCreateForm((p) => ({ ...p, notes: e.target.value }))}
            />
          </div>

          <div className="mc-modal-foot">
            <button className="mc-btn" onClick={() => setIsCreateOpen(false)} type="button">
              Cancel
            </button>
            <button className="mc-btn primary" onClick={saveCreate} type="button">
              Create
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div className="mc-modal-backdrop" role="dialog" aria-modal="true" onMouseDown={onClose}>
      <div className="mc-modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="mc-modal-head">
          <h3 className="mc-modal-title">{title}</h3>
          <button className="mc-btn icon" type="button" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="mc-modal-body">{children}</div>
      </div>
    </div>
  );
}
