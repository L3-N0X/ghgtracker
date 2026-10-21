<script lang="ts">
	import type { Dimension } from '$lib/api/types';
	import { CompressedTime, gapLevel, JUMP_SECONDS, type TravelPoint } from '$lib/map/travel';
	import { formatDateTime, formatSpan, formatTime } from '$lib/format';

	let {
		points,
		dimension,
		brush = $bindable(null),
		hoveredId = $bindable(null),
	}: {
		/** every point in the time range (all dimensions), in time order */
		points: TravelPoint[];
		dimension: Dimension;
		/** selected time window [start ms, end ms] */
		brush?: [number, number] | null;
		hoveredId?: number | null;
	} = $props();

	const HEIGHT = 66;
	const PAD = 12;
	const BASE_Y = 30;

	let svg = $state<SVGSVGElement | null>(null);
	let width = $state(800);
	let dragFrom = $state<number | null>(null);
	let dragTo = $state<number | null>(null);

	// Time jumps longer than JUMP_SECONDS only get JUMP_SECONDS of width, with a break mark.
	const axis = $derived(new CompressedTime(points.map((p) => p.t), JUMP_SECONDS));
	const inner = $derived(Math.max(1, width - 2 * PAD));
	const ux = (t: number) => PAD + axis.toUnit(t) * inner;
	const tx = (px: number) => axis.fromUnit((px - PAD) / inner);

	const multiDay = $derived(
		points.length > 1 && new Date(points[0].t).toDateString() !== new Date(points[points.length - 1].t).toDateString(),
	);

	const hops = $derived(
		points.slice(1).map((p, i) => {
			const prev = points[i];
			const seconds = (p.t - prev.t) / 1000;
			return { key: p.snapshot.id, x1: ux(prev.t), x2: ux(p.t), level: gapLevel(seconds, p.snapshot.session_id !== prev.snapshot.session_id) };
		}),
	);

	const ticks = $derived.by(() => {
		if (points.length < 2) return [];
		const count = Math.max(2, Math.floor(inner / 130));
		return Array.from({ length: count + 1 }, (_, i) => {
			const x = PAD + (i / count) * inner;
			return { x, label: (multiDay ? formatDateTime : formatTime)(new Date(tx(x)).toISOString()), anchor: i === 0 ? 'start' : i === count ? 'end' : 'middle' };
		});
	});

	const brushPx = $derived.by(() => {
		if (dragFrom !== null && dragTo !== null) return [Math.min(dragFrom, dragTo), Math.max(dragFrom, dragTo)];
		if (brush) return [ux(brush[0]), ux(brush[1])];
		return null;
	});

	function localX(event: PointerEvent) {
		return Math.min(width - PAD, Math.max(PAD, event.clientX - svg!.getBoundingClientRect().left));
	}

	function nearest(px: number): TravelPoint | null {
		let best: TravelPoint | null = null;
		let bestDist = 8;
		for (const p of points) {
			const d = Math.abs(ux(p.t) - px);
			if (d < bestDist) {
				best = p;
				bestDist = d;
			}
		}
		return best;
	}

	function onPointerDown(event: PointerEvent) {
		if (event.button !== 0 || points.length < 2) return;
		dragFrom = dragTo = localX(event);
		svg!.setPointerCapture(event.pointerId);
	}

	function onPointerMove(event: PointerEvent) {
		const x = localX(event);
		if (dragFrom !== null) {
			dragTo = x;
			return;
		}
		hoveredId = nearest(x)?.snapshot.id ?? null;
	}

	function onPointerUp() {
		if (dragFrom === null || dragTo === null) return;
		const [a, b] = [Math.min(dragFrom, dragTo), Math.max(dragFrom, dragTo)];
		dragFrom = dragTo = null;
		// A click (no drag) clears the selection.
		brush = b - a < 4 ? null : [tx(a), tx(b)];
	}
</script>

<div class="relative" bind:clientWidth={width}>
	<svg
		bind:this={svg}
		{width}
		height={HEIGHT}
		class="block cursor-crosshair touch-none select-none"
		role="slider"
		aria-label="Timeline. Drag to show only part of the path on the map, click to show everything."
		aria-valuemin={points[0]?.t ?? 0}
		aria-valuemax={points.at(-1)?.t ?? 0}
		aria-valuenow={brush?.[0] ?? points[0]?.t ?? 0}
		tabindex="-1"
		onpointerdown={onPointerDown}
		onpointermove={onPointerMove}
		onpointerup={onPointerUp}
		onpointercancel={onPointerUp}
		onpointerleave={() => dragFrom === null && (hoveredId = null)}
	>
		{#if brushPx}
			<rect x={brushPx[0]} y="4" width={Math.max(1, brushPx[1] - brushPx[0])} height={BASE_Y + 8} rx="4" fill="var(--foreground)" opacity="0.08" />
			<line x1={brushPx[0]} x2={brushPx[0]} y1="4" y2={BASE_Y + 12} stroke="var(--muted-foreground)" />
			<line x1={brushPx[1]} x2={brushPx[1]} y1="4" y2={BASE_Y + 12} stroke="var(--muted-foreground)" />
		{/if}

		<!-- time between readings, same colours as the map path -->
		<g stroke-linecap="round">
			{#each hops as hop (hop.key)}
				<line x1={hop.x1} x2={hop.x2} y1={BASE_Y} y2={BASE_Y} stroke="var(--map-gap-{hop.level})" stroke-width="4" />
			{/each}
		</g>

		<!-- shortened time jumps -->
		{#each axis.breaks as gap (gap.t0)}
			{@const x = PAD + ((gap.u0 + gap.u1) / 2 / axis.total) * inner}
			<g>
				<path d="M {x - 4} {BASE_Y + 6} L {x} {BASE_Y - 6} M {x} {BASE_Y + 6} L {x + 4} {BASE_Y - 6}" stroke="var(--card)" stroke-width="5" />
				<path d="M {x - 4} {BASE_Y + 6} L {x} {BASE_Y - 6} M {x} {BASE_Y + 6} L {x + 4} {BASE_Y - 6}" stroke="var(--muted-foreground)" stroke-width="1.5" />
				<text {x} y="10" text-anchor="middle" class="text-[10px] tabular-nums" fill="var(--muted-foreground)">{formatSpan((gap.t1 - gap.t0) / 1000)}</text>
			</g>
		{/each}

		<!-- one tick per reading; other dimensions are muted -->
		{#each points as p (p.snapshot.id)}
			{@const x = ux(p.t)}
			{@const own = p.dimension === dimension}
			<line
				x1={x} x2={x}
				y1={BASE_Y - (own ? 12 : 8)} y2={BASE_Y - 4}
				stroke={own ? 'var(--foreground)' : 'var(--muted-foreground)'}
				stroke-width="1"
				opacity={own ? 0.45 : 0.3}
			/>
		{/each}
		{#each points.filter((p) => p.snapshot.id === hoveredId) as p (p.snapshot.id)}
			<line x1={ux(p.t)} x2={ux(p.t)} y1={BASE_Y - 14} y2={BASE_Y + 6} stroke="var(--foreground)" stroke-width="2" />
		{/each}

		{#each ticks as tick (tick.x)}
			<text x={tick.x} y={HEIGHT - 6} text-anchor={tick.anchor} class="text-[10px] tabular-nums" fill="var(--muted-foreground)">{tick.label}</text>
		{/each}
	</svg>
</div>
