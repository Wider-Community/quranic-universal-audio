/**
 * Shared types for the stats panel components (StatsPanel, StatsChart,
 * ChartFullscreen). Extracted so both components can import without
 * creating a circular dependency.
 */

/** Distribution data from the API. */
export interface Distribution {
    bins: number[];
    counts: number[];
    percentiles?: Record<string, number>;
}

/** A single annotation line on a chart. */
export interface ChartRefLine {
    value: number;
    label: string;
    /** Stroke colour. Defaults to '#f44336' when omitted. */
    color?: string;
    /** Border dash pattern. Defaults to [4, 3]. */
    dash?: [number, number];
}

/** Configuration for one chart card. */
export interface ChartCfg {
    key: string;
    title: string;
    /** Single ref-line (legacy). Combined with ``refLines`` at render time. */
    refLine?: number;
    refLabel?: string;
    /** Multiple ref-lines (e.g. min_silence + min_silence_floor). */
    refLines?: ChartRefLine[];
    barColor: (bin: number, i?: number, bins?: number[]) => string;
    formatBin?: (v: number) => string;
    showAllLabels?: boolean;
}
