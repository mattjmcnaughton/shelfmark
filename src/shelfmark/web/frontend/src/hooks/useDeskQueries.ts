import { useQuery } from "@tanstack/react-query";
import {
  ApiError,
  type ItemDetail,
  type ItemSummary,
  type Library,
  type Settings,
  type View,
  api,
  itemsPath,
} from "../lib/api";

export const keys = {
  library: ["library"] as const,
  items: ["items"] as const,
  view: (view: View) => ["items", view] as const,
  item: (id: number) => ["item", id] as const,
  settings: ["settings"] as const,
};

// Retry network and server hiccups, but not client, auth, or "not configured" (503) errors.
const retry = (count: number, error: Error) =>
  count < 2 && !(error instanceof ApiError && (error.status < 500 || error.status === 503));

export function useLibrary() {
  return useQuery({
    queryKey: keys.library,
    queryFn: () => api<Library>("/api/library"),
    retry,
  });
}

export function useItems(view: View, enabled: boolean) {
  return useQuery({
    queryKey: keys.view(view),
    queryFn: async () => (await api<{ items: ItemSummary[] }>(itemsPath(view))).items,
    enabled,
    retry,
  });
}

export function useItem(id: number | undefined) {
  return useQuery({
    queryKey: keys.item(id ?? -1),
    queryFn: () => api<ItemDetail>(`/api/items/${id}`),
    enabled: id !== undefined,
    retry,
  });
}

export function useSettings(enabled: boolean) {
  return useQuery({
    queryKey: keys.settings,
    queryFn: () => api<Settings>("/api/settings"),
    enabled,
    retry,
  });
}
