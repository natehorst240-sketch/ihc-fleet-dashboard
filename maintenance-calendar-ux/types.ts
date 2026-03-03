export type ViewMode = "month" | "week" | "day";

export type AircraftOption = {
  id: string;
  registration: string;
};

export type CalendarEvent = {
  id: string;

  // Optional but recommended for filtering + display.
  aircraftId?: string;
  registration?: string;

  // Optional but recommended for filtering + display.
  inspectionType?: string;

  // Required: YYYY-MM-DD
  dueDate: string;

  // Required: drives color coding and the badges.
  hoursRemaining: number;

  notes?: string;
};

export type MaintenanceCalendarProps = {
  initialEvents: CalendarEvent[];

  initialDate?: Date;

  aircraft?: AircraftOption[];
  inspectionTypes?: string[];

  onEventsChange?: (events: CalendarEvent[]) => void;

  /**
   * Locale for date labels (default: "en-US")
   */
  locale?: string;

  /**
   * If true (default), user can drag and drop events in Month/Week views.
   */
  enableDragDrop?: boolean;
};
