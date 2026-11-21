export const dateLabel = (date: string | null) =>
  date ? new Date(date).toLocaleDateString(undefined, { dateStyle: "medium" }) : "Undated";
