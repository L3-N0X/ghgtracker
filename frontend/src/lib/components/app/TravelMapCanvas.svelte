<script lang="ts">
	import PlusIcon from '@lucide/svelte/icons/plus';
	import MinusIcon from '@lucide/svelte/icons/minus';
	import ScanIcon from '@lucide/svelte/icons/scan';
	import LocateFixedIcon from '@lucide/svelte/icons/locate-fixed';
	import * as Tooltip from '$lib/components/ui/tooltip';
	import { Button } from '$lib/components/ui/button';
	import OcrStatusBadge from './OcrStatusBadge.svelte';
	import type { Snapshot } from '$lib/api/types';
	import {
		describeSpeed,
		niceStep,
		prettyBiome,
		type RecentHeading,
		type TravelPoint,
		type TravelSegment,
	} from '$lib/map/travel';
	import { formatBlocks, formatCoord, formatDateTime, formatDuration, formatRelative, formatSpan } from '$lib/format';
	import { now } from '$lib/stores/clock.svelte';
	import { cn } from '$lib/utils';

	let {
		points,
		segments,
		heading,
		hoveredId = $bindable(null),
		fitKey,
		follow = $bindable(true),
		onOpen,
		class: className,
	}: {
		/** points of the shown dimension, in time order */
		points: TravelPoint[];
		segments: TravelSegment[];
		heading: RecentHeading | null;
		hoveredId?: number | null;
		/** the view is fitted to all points whenever this changes */
		fitKey: string;
		follow?: boolean;
		onOpen: (snapshot: Snapshot) => void;
		class?: string;
	} = $props();

	const MIN_SCALE = 0.0005; // px per block
	const MAX_SCALE = 48;
	const POINT_HIT = 14;
	const SEGMENT_HIT = 7;

	let svg = $state<SVGSVGElement | null>(null);
	let width = $state(800);
	let height = $state(520);
	let view = $state({ cx: 0, cz: 0, scale: 1 });
	let hoveredSegment = $state<TravelSegment | null>(null);
	let pointer = $state({ x: 0, y: 0 });
	let drag: { id: number; x: number; y: number; cx: number; cz: number; moved: boolean } | null = null;
	let panning = $state(false);

	const sx = (x: number) => (x - view.cx) * view.scale + width / 2;
	const sy = (z: number) => (z - view.cz) * view.scale + height / 2;
	const wx = (px: number) => (px - width / 2) / view.scale + view.cx;
	const wz = (py: number) => (py - height / 2) / view.scale + view.cz;

	const indexById = $derived(new Map(points.map((p, i) => [p.snapshot.id, i])));
	const hoveredIndex = $derived(hoveredId === null ? -1 : (indexById.get(hoveredId) ?? -1));
	const hovered = $derived(hoveredIndex >= 0 ? points[hoveredIndex] : null);
	const latest = $derived(points.at(-1) ?? null);
	/** segment that ends at a point, by snapshot id */
	const segmentTo = $derived(new Map(segments.map((s) => [s.to.snapshot.id, s])));

	// Older parts of the path fade out so the recent direction stands out.
	const t0 = $derived(points[0]?.t ?? 0);
	const tSpan = $derived(Math.max(1, (latest?.t ?? 0) - t0));
	const age = (t: number) => 0.3 + 0.7 * ((t - t0) / tSpan);

	function fit() {
		if (points.length === 0) return;
		let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
		for (const p of points) {
			minX = Math.min(minX, p.x);
			maxX = Math.max(maxX, p.x);
			minZ = Math.min(minZ, p.z);
			maxZ = Math.max(maxZ, p.z);
		}
		const pad = 56;
		const spanX = Math.max(maxX - minX, 48);
		const spanZ = Math.max(maxZ - minZ, 48);
		const scale = Math.min((width - 2 * pad) / spanX, (height - 2 * pad) / spanZ);
		view = {
			cx: (minX + maxX) / 2,
			cz: (minZ + maxZ) / 2,
			scale: Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale)),
		};
	}

	// Refit when the filters change or the first points arrive.
	let fittedFor = '';
	$effect(() => {
		const key = `${fitKey}|${points.length > 0}`;
		void width;
		if (key !== fittedFor && points.length > 0 && width > 0) {
			fittedFor = key;
			fit();
		}
	});

	// Follow the newest point: pan to it if it would leave the view.
	let followedId: number | null = null;
	$effect(() => {
		const p = latest;
		if (!p || !follow || p.snapshot.id === followedId) return;
		const first = followedId === null;
		followedId = p.snapshot.id;
		if (first) return;
		const margin = 48;
		const x = sx(p.x);
		const y = sy(p.z);
		if (x < margin || x > width - margin || y < margin || y > height - margin) {
			view = { ...view, cx: p.x, cz: p.z };
		}
	});

	function zoomAt(factor: number, px = width / 2, py = height / 2) {
		const scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, view.scale * factor));
		const x = wx(px);
		const z = wz(py);
		view = { scale, cx: x - (px - width / 2) / scale, cz: z - (py - height / 2) / scale };
	}

	$effect(() => {
		if (!svg) return;
		const el = svg;
		const onWheel = (event: WheelEvent) => {
			event.preventDefault();
			const rect = el.getBoundingClientRect();
			const delta = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY;
			zoomAt(Math.exp(-delta * 0.0015), event.clientX - rect.left, event.clientY - rect.top);
		};
		el.addEventListener('wheel', onWheel, { passive: false });
		return () => el.removeEventListener('wheel', onWheel);
	});

	function distToSegment(px: number, py: number, ax: number, ay: number, bx: number, by: number) {
		const dx = bx - ax;
		const dy = by - ay;
		const len2 = dx * dx + dy * dy;
		const f = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
		return Math.hypot(px - (ax + f * dx), py - (ay + f * dy));
	}

	function pick(px: number, py: number) {
		let best: TravelPoint | null = null;
		let bestDist = POINT_HIT;
		// Newest first, so the latest of overlapping points wins.
		for (let i = points.length - 1; i >= 0; i--) {
			const p = points[i];
			const d = Math.hypot(sx(p.x) - px, sy(p.z) - py);
			if (d < bestDist) {
				best = p;
				bestDist = d;
			}
		}
		if (best) return { point: best, segment: null };
		let seg: TravelSegment | null = null;
		let segDist = SEGMENT_HIT;
		for (const s of segments) {
			const d = distToSegment(px, py, sx(s.from.x), sy(s.from.z), sx(s.to.x), sy(s.to.z));
			if (d < segDist) {
				seg = s;
				segDist = d;
			}
		}
		return { point: null, segment: seg };
	}

	function localPos(event: PointerEvent) {
		const rect = svg!.getBoundingClientRect();
		return { x: event.clientX - rect.left, y: event.clientY - rect.top };
	}

	function onPointerDown(event: PointerEvent) {
		if (event.button !== 0) return;
		const pos = localPos(event);
		drag = { id: event.pointerId, ...pos, cx: view.cx, cz: view.cz, moved: false };
		svg!.setPointerCapture(event.pointerId);
	}

	function onPointerMove(event: PointerEvent) {
		const pos = localPos(event);
		pointer = pos;
		if (drag && drag.id === event.pointerId) {
			const dx = pos.x - drag.x;
			const dy = pos.y - drag.y;
			if (!drag.moved && Math.hypot(dx, dy) > 4) {
				drag.moved = true;
				panning = true;
				hoveredId = null;
				hoveredSegment = null;
			}
			if (drag.moved) {
				view = { ...view, cx: drag.cx - dx / view.scale, cz: drag.cz - dy / view.scale };
				return;
			}
		}
		const hit = pick(pos.x, pos.y);
		hoveredId = hit.point?.snapshot.id ?? null;
		hoveredSegment = hit.segment;
	}

	function onPointerUp(event: PointerEvent) {
		if (!drag || drag.id !== event.pointerId) return;
		const wasDrag = drag.moved;
		drag = null;
		panning = false;
		if (wasDrag) return;
		const pos = localPos(event);
		const hit = pick(pos.x, pos.y);
		if (hit.point) onOpen(hit.point.snapshot);
	}

	function onPointerLeave() {
		if (drag) return;
		hoveredId = null;
		hoveredSegment = null;
	}

	function onKeyDown(event: KeyboardEvent) {
		if (points.length === 0) return;
		const step = (dir: number) => {
			const i = hoveredIndex < 0 ? (dir > 0 ? -1 : points.length) : hoveredIndex;
			const next = points[Math.min(points.length - 1, Math.max(0, i + dir))];
			hoveredId = next.snapshot.id;
			hoveredSegment = null;
			const x = sx(next.x);
			const y = sy(next.z);
			if (x < 24 || x > width - 24 || y < 24 || y > height - 24) view = { ...view, cx: next.x, cz: next.z };
		};
		const actions: Record<string, () => void> = {
			ArrowRight: () => step(1),
			ArrowLeft: () => step(-1),
			Home: () => step(-points.length),
			End: () => step(points.length),
			Enter: () => hovered && onOpen(hovered.snapshot),
			'+': () => zoomAt(1.4),
			'=': () => zoomAt(1.4),
			'-': () => zoomAt(1 / 1.4),
			f: fit,
		};
		const action = actions[event.key];
		if (action) {
			event.preventDefault();
			action();
		}
	}

	// ---------------------------------------------------------------- grid

	const grid = $derived.by(() => {
		const step = niceStep(90 / view.scale);
		const x0 = Math.ceil(wx(0) / step) * step;
		const z0 = Math.ceil(wz(0) / step) * step;
		const xs: number[] = [];
		const zs: number[] = [];
		for (let x = x0; x <= wx(width) && xs.length < 200; x += step) xs.push(x);
		for (let z = z0; z <= wz(height) && zs.length < 200; z += step) zs.push(z);
		return { step, xs, zs };
	});

	const scaleBar = $derived.by(() => {
		const blocks = niceStep(110 / view.scale);
		return { blocks, px: blocks * view.scale };
	});

	const fmtAxis = (v: number) => (Math.abs(v) >= 10000 ? `${v / 1000}k` : String(Math.round(v)));

	// ---------------------------------------------------------------- marks

	const visible = (x: number, y: number, m = 40) => x > -m && x < width + m && y > -m && y < height + m;

	const segmentMarks = $derived.by(() =>
		segments.flatMap((seg) => {
			const x1 = sx(seg.from.x), y1 = sy(seg.from.z), x2 = sx(seg.to.x), y2 = sy(seg.to.z);
			if (
				(x1 < 0 && x2 < 0) || (x1 > width && x2 > width) ||
				(y1 < 0 && y2 < 0) || (y1 > height && y2 > height)
			) return [];
			const len = Math.hypot(x2 - x1, y2 - y1);
			return [{ seg, x1, y1, x2, y2, len, angle: (Math.atan2(y2 - y1, x2 - x1) * 180) / Math.PI, opacity: age(seg.to.t) }];
		}),
	);

	// When zoomed out, dots closer than MIN_DOT_GAP px to the last drawn one are skipped so the
	// path stays readable. They can still be hovered and clicked.
	const MIN_DOT_GAP = 18;
	const pointMarks = $derived.by(() => {
		const marks: { p: TravelPoint; x: number; y: number; i: number; opacity: number }[] = [];
		let lastX = -Infinity, lastY = -Infinity;
		points.forEach((p, i) => {
			const x = sx(p.x), y = sy(p.z);
			if (!visible(x, y)) return;
			const keep = i === 0 || p === latest || p === hovered || Math.hypot(x - lastX, y - lastY) >= MIN_DOT_GAP;
			if (!keep) return;
			marks.push({ p, x, y, i, opacity: age(p.t) });
			lastX = x;
			lastY = y;
		});
		return marks;
	});

	const headingMark = $derived.by(() => {
		if (!heading || !latest || heading.to !== latest) return null;
		const x = sx(latest.x), y = sy(latest.z);
		const ux = heading.dx / heading.distance, uz = heading.dz / heading.distance;
		const len = 64;
		return { x1: x + ux * 10, y1: y + uz * 10, x2: x + ux * len, y2: y + uz * len, lx: x + ux * (len + 16), ly: y + uz * (len + 16) };
	});

	function jumpLabel(seg: TravelSegment): string {
		const span = `+${formatSpan(seg.seconds)}`;
		if (seg.via) return `${span} · via ${seg.via}`;
		return seg.newSession ? `${span} · new session` : span;
	}

	const dash = ['', '6 5', '1.5 5'];

	// ---------------------------------------------------------------- tooltip

	const tip = $derived.by(() => {
		if (panning) return null;
		if (hovered) {
			return { kind: 'point' as const, x: sx(hovered.x), y: sy(hovered.z), point: hovered, prev: segmentTo.get(hovered.snapshot.id) ?? null };
		}
		if (hoveredSegment) return { kind: 'segment' as const, x: pointer.x, y: pointer.y, segment: hoveredSegment };
		return null;
	});

	const TIP_W = 264;
	const tipStyle = $derived.by(() => {
		if (!tip) return '';
		const left = tip.x + 16 + TIP_W > width ? tip.x - 16 - TIP_W : tip.x + 16;
		const top = Math.min(Math.max(8, tip.y - 40), height - 200);
		return `left:${Math.max(8, left)}px;top:${top}px;width:${TIP_W}px`;
	});
</script>

<div
	class={cn('relative overflow-hidden rounded-lg border bg-muted/20 select-none', className)}
	bind:clientWidth={width}
	bind:clientHeight={height}
>
	<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
	<svg
		bind:this={svg}
		{width}
		{height}
		role="application"
		aria-label="Travel map. Arrow keys step through the points, Enter opens the snapshot, + and - zoom, F fits the path."
		tabindex="0"
		class={cn('absolute inset-0 block touch-none outline-none focus-visible:ring-2 focus-visible:ring-ring', panning ? 'cursor-grabbing' : hovered ? 'cursor-pointer' : 'cursor-grab')}
		onpointerdown={onPointerDown}
		onpointermove={onPointerMove}
		onpointerup={onPointerUp}
		onpointercancel={onPointerUp}
		onpointerleave={onPointerLeave}
		onkeydown={onKeyDown}
	>
		<defs>
			<marker id="heading-head" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
				<path d="M 0 0 L 10 5 L 0 10 z" fill="var(--foreground)" />
			</marker>
		</defs>

		<!-- grid -->
		<g class="text-[10px] tabular-nums" fill="var(--muted-foreground)">
			{#each grid.xs as x (x)}
				<line x1={sx(x)} x2={sx(x)} y1="0" y2={height} stroke="var(--border)" stroke-width={x === 0 ? 1.5 : 1} />
				<text x={sx(x) + 3} y="12">{fmtAxis(x)}</text>
			{/each}
			{#each grid.zs as z (z)}
				<line x1="0" x2={width} y1={sy(z)} y2={sy(z)} stroke="var(--border)" stroke-width={z === 0 ? 1.5 : 1} />
				<text x="4" y={sy(z) - 3}>{fmtAxis(z)}</text>
			{/each}
		</g>

		<!-- path: one line per hop, styled by the time that passed -->
		<g fill="none" stroke-linecap="round">
			{#each segmentMarks as m (m.seg.to.snapshot.id)}
				<line
					x1={m.x1} y1={m.y1} x2={m.x2} y2={m.y2}
					stroke="var(--map-gap-{m.seg.level})"
					stroke-width={hoveredSegment === m.seg ? 4 : 2}
					stroke-dasharray={dash[m.seg.level]}
					opacity={hoveredSegment === m.seg ? 1 : m.opacity}
				/>
				{#if m.len > 40 && m.seg.level === 0}
					<path
						d="M -3.5 -4 L 1.5 0 L -3.5 4"
						transform="translate({(m.x1 + m.x2) / 2} {(m.y1 + m.y2) / 2}) rotate({m.angle})"
						stroke="var(--map-gap-0)"
						stroke-width="2"
						stroke-linejoin="round"
						opacity={m.opacity}
					/>
				{/if}
			{/each}
		</g>

		<!-- heading over the last minutes of continuous travel -->
		{#if headingMark && heading}
			<g pointer-events="none">
				<line
					x1={headingMark.x1} y1={headingMark.y1} x2={headingMark.x2} y2={headingMark.y2}
					stroke="var(--foreground)" stroke-width="2" stroke-dasharray="4 4" marker-end="url(#heading-head)"
				/>
				<text
					x={headingMark.lx} y={headingMark.ly} dy="0.35em" text-anchor="middle"
					class="text-[11px] font-semibold halo" fill="var(--foreground)"
				>{heading.direction}</text>
			</g>
		{/if}

		<!-- points -->
		<g>
			{#each pointMarks as m (m.p.snapshot.id)}
				{@const isLatest = m.p === latest}
				{@const isHovered = m.p === hovered}
				{@const unverified = m.p.snapshot.ocr_status === 'unverified'}
				{#if isLatest}
					<circle cx={m.x} cy={m.y} r="12" fill="var(--map-gap-0)" opacity="0.25" class="pulse" />
				{/if}
				<circle
					cx={m.x}
					cy={m.y}
					r={isHovered ? 6.5 : isLatest ? 6 : 4.5}
					fill={unverified ? 'var(--card)' : isLatest ? 'var(--map-gap-0)' : 'var(--foreground)'}
					stroke={unverified ? 'var(--foreground)' : 'var(--card)'}
					stroke-width={unverified ? 1.5 : 2}
					opacity={isHovered || isLatest ? 1 : m.opacity}
				/>
				{#if m.i === 0 && points.length > 1}
					<text x={m.x} y={m.y - 10} text-anchor="middle" class="halo text-[10px]" fill="var(--muted-foreground)">start</text>
				{/if}
			{/each}
		</g>

		<!-- time jump labels on top, so they stay readable -->
		<g pointer-events="none">
			{#each segmentMarks as m (m.seg.to.snapshot.id)}
				{#if m.seg.level === 2 && m.len > 90}
					<text
						x={(m.x1 + m.x2) / 2} y={(m.y1 + m.y2) / 2} dy="-0.6em" text-anchor="middle"
						class="halo text-[10px] tabular-nums" fill="var(--muted-foreground)"
					>{jumpLabel(m.seg)}</text>
				{/if}
			{/each}
		</g>
	</svg>

	<!-- compass + scale -->
	<div class="pointer-events-none absolute bottom-3 left-3 flex items-end gap-3 text-[10px] text-muted-foreground">
		<div class="flex flex-col items-center leading-none font-semibold">
			<span class="text-foreground">N</span>
			<span>↑</span>
		</div>
		<div>
			<div class="h-1.5 border-x border-b border-muted-foreground" style="width:{scaleBar.px}px"></div>
			<div class="mt-0.5 tabular-nums">{scaleBar.blocks.toLocaleString()} blocks</div>
		</div>
	</div>

	<!-- view controls -->
	<div class="absolute top-3 right-3 flex flex-col gap-1">
		<Tooltip.Root>
			<Tooltip.Trigger>
				{#snippet child({ props })}
					<Button {...props} variant="outline" size="icon-sm" aria-label="Zoom in" onclick={() => zoomAt(1.5)}><PlusIcon /></Button>
				{/snippet}
			</Tooltip.Trigger>
			<Tooltip.Content side="left">Zoom in (+)</Tooltip.Content>
		</Tooltip.Root>
		<Tooltip.Root>
			<Tooltip.Trigger>
				{#snippet child({ props })}
					<Button {...props} variant="outline" size="icon-sm" aria-label="Zoom out" onclick={() => zoomAt(1 / 1.5)}><MinusIcon /></Button>
				{/snippet}
			</Tooltip.Trigger>
			<Tooltip.Content side="left">Zoom out (−)</Tooltip.Content>
		</Tooltip.Root>
		<Tooltip.Root>
			<Tooltip.Trigger>
				{#snippet child({ props })}
					<Button {...props} variant="outline" size="icon-sm" aria-label="Fit path" onclick={fit}><ScanIcon /></Button>
				{/snippet}
			</Tooltip.Trigger>
			<Tooltip.Content side="left">Fit the whole path (F)</Tooltip.Content>
		</Tooltip.Root>
		<Tooltip.Root>
			<Tooltip.Trigger>
				{#snippet child({ props })}
					<Button
						{...props}
						variant={follow ? 'secondary' : 'outline'}
						size="icon-sm"
						aria-label="Follow latest position"
						aria-pressed={follow}
						onclick={() => {
							follow = !follow;
							if (follow && latest) view = { ...view, cx: latest.x, cz: latest.z };
						}}
					>
						<LocateFixedIcon class={follow ? 'text-[var(--map-gap-0)]' : ''} />
					</Button>
				{/snippet}
			</Tooltip.Trigger>
			<Tooltip.Content side="left">{follow ? 'Following new positions' : 'Follow new positions'}</Tooltip.Content>
		</Tooltip.Root>
	</div>

	<!-- hover details -->
	{#if tip}
		<div class="pointer-events-none absolute z-10 rounded-lg border bg-popover p-3 text-xs text-popover-foreground shadow-lg" style={tipStyle}>
			{#if tip.kind === 'point'}
				{@const s = tip.point.snapshot}
				<div class="flex items-start justify-between gap-2">
					<div class="min-w-0">
						<div class="truncate text-sm font-semibold">{prettyBiome(s.biome)}</div>
						<div class="text-muted-foreground capitalize">{tip.point.dimension}{s.facing ? ` · facing ${s.facing}` : ''}</div>
					</div>
					<OcrStatusBadge status={s.ocr_status} />
				</div>
				<div class="mt-2 grid grid-cols-3 gap-1 font-mono tabular-nums">
					<div><span class="text-muted-foreground">X </span><span class="font-semibold">{formatCoord(s.x)}</span></div>
					<div><span class="text-muted-foreground">Y </span><span class="font-semibold">{formatCoord(s.y)}</span></div>
					<div><span class="text-muted-foreground">Z </span><span class="font-semibold">{formatCoord(s.z)}</span></div>
				</div>
				<div class="mt-2 space-y-0.5 tabular-nums">
					<div><span class="font-medium">{formatDateTime(s.captured_at)}</span> <span class="text-muted-foreground">· {formatRelative(s.captured_at, now.current)}</span></div>
					<div class="text-muted-foreground">Session #{s.session_id} · {formatDuration(s.stream_offset_seconds)} into the stream</div>
					{#if tip.prev}
						<div class="flex items-center gap-1.5 pt-1">
							<svg width="16" height="4" class="shrink-0" aria-hidden="true">
								<line x1="1" y1="2" x2="15" y2="2" stroke="var(--map-gap-{tip.prev.level})" stroke-width="2" stroke-dasharray={dash[tip.prev.level]} stroke-linecap="round" />
							</svg>
							<span><span class="font-medium">+{formatSpan(tip.prev.seconds)}</span> <span class="text-muted-foreground">· {formatBlocks(tip.prev.distance)} since previous</span></span>
						</div>
					{/if}
				</div>
				<div class="mt-2 border-t pt-2 text-muted-foreground">Click to open the snapshot</div>
			{:else}
				{@const seg = tip.segment}
				<div class="flex items-center gap-1.5">
					<svg width="16" height="4" class="shrink-0" aria-hidden="true">
						<line x1="1" y1="2" x2="15" y2="2" stroke="var(--map-gap-{seg.level})" stroke-width="2" stroke-dasharray={dash[seg.level]} stroke-linecap="round" />
					</svg>
					<span class="text-sm font-semibold tabular-nums">+{formatSpan(seg.seconds)}</span>
					<span class="text-muted-foreground">{['continuous', 'pause', 'time jump'][seg.level]}</span>
				</div>
				<div class="mt-2 space-y-0.5 tabular-nums">
					<div><span class="font-medium">{formatBlocks(seg.distance)}</span> <span class="text-muted-foreground">· {Number.isFinite(seg.speed) ? `${seg.speed.toFixed(1)} blocks/s` : '—'}</span></div>
					<div class="text-muted-foreground">{describeSpeed(seg.speed)}</div>
					<div class="text-muted-foreground">{formatDateTime(seg.from.snapshot.captured_at)} → {formatDateTime(seg.to.snapshot.captured_at)}</div>
					{#if seg.newSession}<div class="text-muted-foreground">Stream session changed in between</div>{/if}
					{#if seg.via}<div class="text-muted-foreground capitalize">Visited the {seg.via} in between</div>{/if}
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.halo {
		paint-order: stroke;
		stroke: var(--card);
		stroke-width: 3px;
		stroke-linejoin: round;
	}
	.pulse {
		transform-box: fill-box;
		transform-origin: center;
		animation: pulse 2s ease-out infinite;
	}
	@keyframes pulse {
		from {
			transform: scale(0.5);
			opacity: 0.5;
		}
		to {
			transform: scale(1.6);
			opacity: 0;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.pulse {
			animation: none;
		}
	}
</style>
