import { useState } from "react";
import type { LibrarySort, LibraryView } from "../pages/LibraryPage";

export function useLibraryPreferences() {
  const [view, setView] = useState<LibraryView>(() => {
    try { return localStorage.getItem("sftranslator_library_view") === "grid" ? "grid" : "list"; }
    catch { return "list"; }
  });
  const [sort, setSort] = useState<LibrarySort>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem("sftranslator_library_sort") || "null");
      if (["lastLaunch", "addedAt", "name"].includes(saved?.key) && ["asc", "desc"].includes(saved?.direction)) return saved;
    } catch { /* Default order below. */ }
    return { key: "lastLaunch", direction: "desc" };
  });
  const changeView = (next: LibraryView) => {
    setView(next);
    try { localStorage.setItem("sftranslator_library_view", next); } catch { /* Preview may lack storage. */ }
  };
  const changeSort = (next: LibrarySort) => {
    setSort(next);
    try { localStorage.setItem("sftranslator_library_sort", JSON.stringify(next)); } catch { /* Preview may lack storage. */ }
  };
  return { view, sort, changeView, changeSort };
}
