<script lang="ts">
	import type { TrackerStatus } from '$lib/api/types';
	import { formatDuration, formatNumber } from '$lib/format';
	import { now } from '$lib/stores/clock.svelte';

	let { status }: { status: TrackerStatus | undefined } = $props();

	const active = $derived(status?.state === 'running' || status?.state === 'starting');
	const uptime = $derived(
		status?.started_at && active ? (now.current - new Date(status.started_at).getTime()) / 1000 : null,
	);

	const tiles = $derived([
		{
			label: 'Frames analysed',
			value: formatNumber(status?.frames_processed ?? 0),
			sub: active
				? `${status?.measured_fps.toFixed(1)} fps · ${status?.detect_ms.toFixed(1)} ms/frame`
				: 'current session',
		},
		{
			label: 'F3 openings',
			value: formatNumber(status?.f3_events ?? 0),
			sub: `${formatNumber(status?.f3_frames ?? 0)} frames with F3`,
		},
		{
			label: 'Snapshots saved',
			value: formatNumber(status?.snapshots_saved ?? 0),
			sub: status?.save_interval_seconds != null ? `max. one every ${status.save_interval_seconds} s` : '—',
		},
		{
			label: 'Session time',
			value: uptime !== null ? formatDuration(uptime) : '—',
			sub: status?.session_id ? `session #${status.session_id}` : 'not running',
		},
	]);
</script>

<dl class="grid grid-cols-2 gap-3 lg:grid-cols-4">
	{#each tiles as tile (tile.label)}
		<div class="rounded-xl border bg-card px-4 py-3">
			<dt class="text-xs text-muted-foreground">{tile.label}</dt>
			<dd class="mt-1 text-2xl font-semibold tabular-nums tracking-tight">{tile.value}</dd>
			<dd class="mt-0.5 truncate text-xs text-muted-foreground tabular-nums">{tile.sub}</dd>
		</div>
	{/each}
</dl>
