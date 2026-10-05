"use client";

/**
 * A project server's console, live in the page.
 *
 * xterm.js talks to Sentinel's console relay (manage.py console_proxy), which
 * talks to Proxmox with Sentinel's token - the browser never holds it. The
 * relay is opened with a one-minute pass from the API. Frames use Proxmox's
 * termproxy format: "0:<bytes>:<text>" for keystrokes, "1:<cols>:<rows>:"
 * for a resize and "2" to keep the line open.
 */
import { useEffect, useRef, useState } from "react";
import "@xterm/xterm/css/xterm.css";

type State = "connecting" | "open" | "closed";

export function ServerConsole({ project, serverId }: { project: string; serverId: number }) {
  const box = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<State>("connecting");
  const [reason, setReason] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let disposed = false;
    let ws: WebSocket | null = null;
    let term: import("@xterm/xterm").Terminal | null = null;
    let ping: ReturnType<typeof setInterval> | undefined;
    let watcher: ResizeObserver | null = null;
    const bytes = new TextEncoder();

    void (async () => {
      const [{ Terminal }, { FitAddon }] = await Promise.all([
        import("@xterm/xterm"), import("@xterm/addon-fit"),
      ]);
      if (disposed || !box.current) return;
      term = new Terminal({
        cursorBlink: true, fontSize: 13,
        fontFamily: '"Cascadia Mono", Consolas, ui-monospace, Menlo, monospace',
        theme: { background: "#0b0f14", foreground: "#d6dde6" },
      });
      const fit = new FitAddon();
      term.loadAddon(fit);
      term.open(box.current);
      fit.fit();
      term.writeln("Connecting to the server console…");

      const r = await fetch(
        `/api/projects/${encodeURIComponent(project)}/servers/${serverId}/console`, { method: "POST" });
      const d = await r.json().catch(() => ({}));
      if (disposed) return;
      if (!r.ok) {
        setState("closed");
        setReason(d.detail || "Could not open the console.");
        return;
      }

      ws = new WebSocket(d.url);
      ws.binaryType = "arraybuffer";
      const send = (s: string) => { if (ws?.readyState === WebSocket.OPEN) ws.send(s); };
      const resize = () => {
        if (!term) return;
        fit.fit();
        send(`1:${term.cols}:${term.rows}:`);
      };
      ws.onopen = () => {
        setState("open");
        term?.reset();
        resize();
        term?.focus();
        // A serial console shows nothing until something is typed; Enter
        // brings the login prompt back.
        send("0:1:\r");
        ping = setInterval(() => send("2"), 30000);
      };
      ws.onmessage = (e) => {
        term?.write(typeof e.data === "string" ? e.data : new Uint8Array(e.data as ArrayBuffer));
      };
      ws.onclose = (e) => {
        clearInterval(ping);
        setState("closed");
        setReason(e.reason || "The console was closed.");
      };
      term.onData((text) => send(`0:${bytes.encode(text).length}:${text}`));
      watcher = new ResizeObserver(() => resize());
      watcher.observe(box.current);
    })();

    return () => {
      disposed = true;
      clearInterval(ping);
      watcher?.disconnect();
      ws?.close();
      term?.dispose();
    };
  }, [project, serverId, attempt]);

  return (
    <div className="overflow-hidden rounded-lg ring-1 ring-stroke">
      <div className="flex items-center gap-2 bg-[#151b23] px-3 py-1.5 text-xs text-[#9aa7b4]">
        <span aria-hidden className={`h-2 w-2 rounded-full ${
          state === "open" ? "bg-[#3fb950]" : state === "connecting" ? "animate-pulse bg-[#d29922]" : "bg-[#6e7681]"}`} />
        <span className="flex-1">
          {state === "open" ? "Connected - serial console"
            : state === "connecting" ? "Connecting…" : reason || "Disconnected"}
        </span>
        {state === "closed" && (
          <button onClick={() => { setState("connecting"); setReason(""); setAttempt((n) => n + 1); }}
                  className="rounded px-2 py-0.5 font-medium text-[#d6dde6] ring-1 ring-[#30363d] hover:bg-[#21262d]">
            Reconnect
          </button>
        )}
      </div>
      <div ref={box} className="h-[420px] bg-[#0b0f14] p-2" />
    </div>
  );
}
