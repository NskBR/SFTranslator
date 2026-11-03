import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";

const DEFAULT_WIDTH = 240;
const COMPACT_WIDTH = 68;
const MIN_WIDTH = 140;
const MAX_WIDTH = 260;

export function useSidebarWidth() {
  const sidebarRef = useRef<HTMLElement>(null);
  const [width, setWidth] = useState(() => {
    try {
      const saved = Number(localStorage.getItem("sftranslator_sidebar_width_v2"));
      if (Number.isFinite(saved) && saved > 0) {
        if (saved <= 90) return COMPACT_WIDTH;
        return Math.min(Math.max(saved, MIN_WIDTH), MAX_WIDTH);
      }
    } catch { /* Preview may lack storage. */ }
    return DEFAULT_WIDTH;
  });
  const [resizing, setResizing] = useState(false);
  const compact = width <= 90;
  const saveWidth = (next: number) => {
    setWidth(next);
    try { localStorage.setItem("sftranslator_sidebar_width_v2", String(next)); } catch { /* Preview may lack storage. */ }
  };
  useEffect(() => {
    if (!resizing) return;
    const move = (event: MouseEvent) => {
      const sidebar = sidebarRef.current;
      if (!sidebar) return;
      const raw = event.clientX - sidebar.getBoundingClientRect().left;
      saveWidth(raw < 115 ? COMPACT_WIDTH : Math.min(Math.max(raw, MIN_WIDTH), MAX_WIDTH));
    };
    const stop = () => setResizing(false);
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", stop);
    return () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", stop); };
  }, [resizing]);
  const startResize = (event: ReactMouseEvent) => { event.preventDefault(); setResizing(true); };
  const toggleWidth = () => saveWidth(compact ? DEFAULT_WIDTH : COMPACT_WIDTH);
  return { sidebarRef, width, resizing, compact, startResize, toggleWidth };
}
