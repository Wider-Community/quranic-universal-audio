// @ts-nocheck — removed per-file as each module is typed in Phases 4+
/**
 * Chart.js bootstrap.
 *
 * Registers all standard chart types, scales, and elements plus the annotation
 * plugin, then re-exports the `Chart` constructor. Consumers should import
 * from here rather than relying on a global — the Phase 2 npm migration
 * replaces the legacy `<script>` CDN load.
 */
import { Chart, registerables } from 'chart.js';
import annotationPlugin from 'chartjs-plugin-annotation';

Chart.register(...registerables, annotationPlugin);

export { Chart };
