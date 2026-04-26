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

/** Configuration for one chart card. */
export interface ChartCfg {
    key: string;
    title: string;
    refLine?: number;
    refLabel?: string;
    barColor: (bin: number, i?: number, bins?: number[]) => string;
    formatBin?: (v: number) => string;
    showAllLabels?: boolean;
}
