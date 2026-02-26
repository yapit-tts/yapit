/**
 * Lightweight performance instrumentation for frontend hot paths.
 *
 * Wraps functions with performance.mark()/measure() and exposes results
 * via window.__yapit_perf for agent access (evaluate_script in DevTools MCP).
 *
 * Dev-only — all exports are no-ops in production builds.
 *
 * Usage in instrumented code:
 *   import { perfWrap } from './perfMonitor';
 *   const measuredFn = perfWrap('deriveBlockStates', originalFn);
 *
 * Usage from DevTools MCP (evaluate_script):
 *   () => window.__yapit_perf.summary()
 *   () => window.__yapit_perf.reset()
 *   () => window.__yapit_perf.measurements('deriveBlockStates')
 */

interface Measurement {
  duration_ms: number;
  timestamp: number;
}

interface FnStats {
  calls: number;
  avg_ms: number;
  p95_ms: number;
  max_ms: number;
  total_ms: number;
  last_ms: number;
}

interface PerfAPI {
  reset: () => void;
  summary: () => Record<string, FnStats>;
  measurements: (name: string) => Measurement[];
}

declare global {
  interface Window {
    __yapit_perf: PerfAPI;
  }
}

const IS_DEV = import.meta.env.DEV;

const store = new Map<string, Measurement[]>();

function record(name: string, duration_ms: number) {
  let entries = store.get(name);
  if (!entries) {
    entries = [];
    store.set(name, entries);
  }
  entries.push({ duration_ms, timestamp: performance.now() });
}

function computeStats(entries: Measurement[]): FnStats {
  if (entries.length === 0) {
    return { calls: 0, avg_ms: 0, p95_ms: 0, max_ms: 0, total_ms: 0, last_ms: 0 };
  }
  const durations = entries.map(e => e.duration_ms).sort((a, b) => a - b);
  const total = durations.reduce((s, d) => s + d, 0);
  const p95Idx = Math.floor(durations.length * 0.95);
  return {
    calls: durations.length,
    avg_ms: Math.round((total / durations.length) * 100) / 100,
    p95_ms: Math.round(durations[p95Idx] * 100) / 100,
    max_ms: Math.round(durations[durations.length - 1] * 100) / 100,
    total_ms: Math.round(total * 100) / 100,
    last_ms: Math.round(durations[durations.length - 1] * 100) / 100,
  };
}

const perfAPI: PerfAPI = {
  reset() {
    store.clear();
  },
  summary() {
    const result: Record<string, FnStats> = {};
    for (const [name, entries] of store) {
      result[name] = computeStats(entries);
    }
    return result;
  },
  measurements(name: string) {
    return store.get(name) ?? [];
  },
};

// Install globally for agent access
if (IS_DEV) {
  window.__yapit_perf = perfAPI;
}

/**
 * Wrap a function with performance measurement. No-op in production.
 *
 * The wrapper has the same signature as the original function.
 */
export function perfWrap<T extends (...args: never[]) => unknown>(
  name: string,
  fn: T,
): T {
  if (!IS_DEV) return fn;

  const wrapped = (...args: Parameters<T>): ReturnType<T> => {
    const start = performance.now();
    const result = fn(...args);
    record(name, performance.now() - start);
    return result as ReturnType<T>;
  };
  return wrapped as unknown as T;
}

/**
 * Measure a block of code inline. No-op in production.
 *
 *   const end = perfStart('filterVisibleBlocks');
 *   // ... work ...
 *   end();
 */
export function perfStart(name: string): () => void {
  if (!IS_DEV) return () => {};
  const start = performance.now();
  return () => record(name, performance.now() - start);
}
