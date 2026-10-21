<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import MapIcon from '@lucide/svelte/icons/map';
	import NavigationIcon from '@lucide/svelte/icons/navigation-2';
	import XIcon from '@lucide/svelte/icons/x';
	import * as Card from '$lib/components/ui/card';
	import * as Select from '$lib/components/ui/select';
	import * as Empty from '$lib/components/ui/empty';
	import { Button } from '$lib/components/ui/button';
	import { Label } from '$lib/components/ui/label';
	import { Switch } from '$lib/components/ui/switch';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import TravelMapCanvas from './TravelMapCanvas.svelte';
	import TravelTimeline from './TravelTimeline.svelte';
	import SnapshotDialog from './SnapshotDialog.svelte';
	import { api } from '$lib/api/client';
	import type { Dimension, Snapshot } from '$lib/api/types';
	import { buildSegments, GAP_LEVELS, recentHeading, toTravelPoints } from '$lib/map/travel';
	import { formatBlocks, formatSpan, formatTime } from '$lib/format';
	import { live } from '$lib/stores/live.svelte';
	import { now } from '$lib/stores/clock.svelte';
	import { cn } from '$lib/utils';

	const PAGE_SIZE = 1000;
	const MAX_POINTS = 20000;

	let { streamerId }: { streamerId: number } = $props();

	const ranges = [
		{ value: '30m', label: 'Last 30 min', seconds: 30 * 60 },
		{ value: '2h', label: 'Last 2 hours', seconds: 2 * 3600 },
		{ value: '12h', label: 'Last 12 hours', seconds: 12 * 3600 },
		{ value: '24h', label: 'Last 24 hours', seconds: 24 * 3600 },
		{ value: '7d', label: 'Last 7 days', seconds: 7 * 86400 },
		{ value: 'all', label: 'All time', seconds: null },
	] as const;
	const dimensionLabels: Record<Dimension, string> = { overworld: 'Overworld', nether: 'Nether', end: 'End' };

	let snapshots = $state<Snapshot[]>([]);
	let loading = $state(true);
	let reloading = $state(false);
	let truncated = $state(false);
	let range = $state<string>('24h');
	let dimensionChoice = $state<'auto' | Dimension>('auto');
	let showUnverified = $state(true);
	let brush = $state<[number, number] | null>(null);
	let hoveredId = $state<number | null>(null);
	let follow = $state(true);
	let selected = $state<Snapshot | null>(null);
	let dialogOpen = $state(false);

	const rangeSeconds = $derived(ranges.find((r) => r.value === range)?.seconds ?? null);

	async function load() {
		if (snapshots.length === 0) loading = true;
		else reloading = true;
		const since = rangeSeconds === null ? undefined : new Date(Date.now() - rangeSeconds * 1000).toISOString();
		try {
			const items: Snapshot[] = [];
			for (let offset = 0; offset < MAX_POINTS; offset += PAGE_SIZE) {
				const page = await api.snapshots.list({
					streamer_id: streamerId,
					has_position: true,
					since,
					order: 'desc',
					limit: PAGE_SIZE,
					offset,
				});
				items.push(...page.items);
				truncated = page.total > MAX_POINTS;
				if (items.length >= page.total) break;
			}
			snapshots = items;
		} finally {
			loading = false;
			reloading = false;
		}
	}

	$effect(() => {
		void rangeSeconds;
		untrack(() => {
			brush = null;
			load();
		});
	});

	onMount(() =>
		live.subscribe((event) => {
			if ((event.type !== 'snapshot.created' && event.type !== 'snapshot.updated') || event.streamer_id !== streamerId) return;
			upsert(event.snapshot);
		}),
	);

	function upsert(snap: Snapshot) {
		const rest = snapshots.filter((s) => s.id !== snap.id);
		snapshots = snap.x !== null && snap.z !== null ? [...rest, snap] : rest;
		if (selected?.id === snap.id) selected = snap;
	}

	// ------------------------------------------------------------------ derived path

	const allPoints = $derived(toTravelPoints(snapshots));
	// The relative time range keeps sliding while the page is open (minute steps are enough).
	const minute = $derived(Math.floor(now.current / 60_000));
	const inRange = $derived(
		allPoints.filter(
			(p) =>
				(rangeSeconds === null || p.t >= minute * 60_000 - rangeSeconds * 1000) &&
				(showUnverified || p.snapshot.ocr_status !== 'unverified'),
		),
	);
	const dimensionCounts = $derived(
		inRange.reduce<Record<Dimension, number>>(
			(acc, p) => ((acc[p.dimension] += 1), acc),
			{ overworld: 0, nether: 0, end: 0 },
		),
	);
	const dimension = $derived<Dimension>(
		dimensionChoice === 'auto' ? (inRange.at(-1)?.dimension ?? 'overworld') : dimensionChoice,
	);
	const windowed = $derived(brush ? inRange.filter((p) => p.t >= brush![0] && p.t <= brush![1]) : inRange);
	const points = $derived(windowed.filter((p) => p.dimension === dimension));
	const segments = $derived(buildSegments(windowed, dimension));
	const heading = $derived(recentHeading(segments));

	const stats = $derived.by(() => {
		const travelled = segments.reduce((sum, s) => sum + (s.level < 2 ? s.distance : 0), 0);
		const jumps = segments.filter((s) => s.level === 2).length;
		const span = points.length > 1 ? (points[points.length - 1].t - points[0].t) / 1000 : 0;
		return { travelled, jumps, span };
	});

	const fitKey = $derived(`${streamerId}|${range}|${dimension}|${brush?.join('-') ?? ''}|${showUnverified}`);

	function open(snapshot: Snapshot) {
		selected = snapshot;
		dialogOpen = true;
	}

	function onDeleted(id: number) {
		snapshots = snapshots.filter((s) => s.id !== id);
	}

	const dash = ['', '6 5', '1.5 5'];
</script>

<Card.Root>
	<Card.Header>
		<Card.Title>Travel map</Card.Title>
		<Card.Description>
			Every position read from the F3 screen, joined in time order. The line style shows how much
			time passed between two readings, so a long line drawn solid really was travelled. Hover a
			dot for details, click it to open the snapshot. Drag on the timeline to look at part of the
			path.
		</Card.Description>
	</Card.Header>
	<Card.Content class="space-y-3">
		<!-- filters -->
		<div class="flex flex-wrap items-center gap-2">
			<Select.Root type="single" bind:value={range}>
				<Select.Trigger size="sm" class="w-36">{ranges.find((r) => r.value === range)?.label}</Select.Trigger>
				<Select.Content>
					{#each ranges as r (r.value)}
						<Select.Item value={r.value} label={r.label} />
					{/each}
				</Select.Content>
			</Select.Root>
			<Select.Root type="single" bind:value={dimensionChoice}>
				<Select.Trigger size="sm" class="w-44">
					{dimensionChoice === 'auto' ? `Current · ${dimensionLabels[dimension]}` : dimensionLabels[dimensionChoice]}
				</Select.Trigger>
				<Select.Content>
					<Select.Item value="auto" label="Current dimension">
						<span>Current dimension</span>
					</Select.Item>
					{#each Object.entries(dimensionLabels) as [value, label] (value)}
						<Select.Item {value} {label}>
							<span>{label}</span>
							<span class="ml-auto text-xs text-muted-foreground tabular-nums">{dimensionCounts[value as Dimension]}</span>
						</Select.Item>
					{/each}
				</Select.Content>
			</Select.Root>
			<div class="flex items-center gap-2 px-1">
				<Switch id="map-unverified" bind:checked={showUnverified} />
				<Label for="map-unverified" class="text-sm font-normal">Unverified readings</Label>
			</div>
			{#if brush}
				<Button variant="secondary" size="sm" class="tabular-nums" onclick={() => (brush = null)}>
					{formatTime(new Date(brush[0]).toISOString())} – {formatTime(new Date(brush[1]).toISOString())}
					<XIcon />
				</Button>
			{/if}
		</div>

		{#if loading}
			<Skeleton class="h-[520px] w-full" />
		{:else if inRange.length === 0}
			<Empty.Root class="h-[520px] border border-dashed">
				<Empty.Header>
					<Empty.Media variant="icon"><MapIcon /></Empty.Media>
					<Empty.Title>No positions {range === 'all' ? 'yet' : 'in this time range'}</Empty.Title>
					<Empty.Description>
						Points appear as soon as OCR reads coordinates from a snapshot.
					</Empty.Description>
				</Empty.Header>
				{#if range !== 'all'}
					<Empty.Content><Button variant="outline" size="sm" onclick={() => (range = 'all')}>Show all time</Button></Empty.Content>
				{/if}
			</Empty.Root>
		{:else}
			<!-- summary -->
			<dl class="flex flex-wrap gap-x-8 gap-y-2 text-sm">
				<div>
					<dt class="text-xs text-muted-foreground">Recent heading</dt>
					<dd class="flex items-center gap-1.5 font-medium">
						{#if heading}
							<NavigationIcon
								class="size-3.5"
								style="transform: rotate({(Math.atan2(heading.dx, -heading.dz) * 180) / Math.PI}deg)"
							/>
							{heading.direction}
							<span class="font-normal text-muted-foreground tabular-nums">
								· {formatBlocks(heading.distance)} in {formatSpan(heading.seconds)}
							</span>
						{:else}
							<span class="font-normal text-muted-foreground">not moving</span>
						{/if}
					</dd>
				</div>
				<div>
					<dt class="text-xs text-muted-foreground">Travelled</dt>
					<dd class="font-medium tabular-nums">{formatBlocks(stats.travelled)}</dd>
				</div>
				<div>
					<dt class="text-xs text-muted-foreground">Positions</dt>
					<dd class="font-medium tabular-nums">
						{points.length.toLocaleString()}
						{#if truncated}<span class="font-normal text-muted-foreground">(newest {MAX_POINTS.toLocaleString()})</span>{/if}
					</dd>
				</div>
				<div>
					<dt class="text-xs text-muted-foreground">Time span</dt>
					<dd class="font-medium tabular-nums">{formatSpan(stats.span)}</dd>
				</div>
				<div>
					<dt class="text-xs text-muted-foreground">Time jumps</dt>
					<dd class="font-medium tabular-nums">{stats.jumps}</dd>
				</div>
			</dl>

			<div class={cn('space-y-2 transition-opacity', reloading && 'opacity-60')}>
				{#if points.length === 0}
					<Empty.Root class="h-[520px] border border-dashed">
						<Empty.Header>
							<Empty.Title>No positions in the {dimensionLabels[dimension]}</Empty.Title>
							<Empty.Description>Pick another dimension or widen the time range.</Empty.Description>
						</Empty.Header>
					</Empty.Root>
				{:else}
					<TravelMapCanvas
						class="h-[520px]"
						{points}
						{segments}
						{heading}
						{fitKey}
						bind:hoveredId
						bind:follow
						onOpen={open}
					/>
				{/if}
				<TravelTimeline points={inRange} {dimension} bind:brush bind:hoveredId />
			</div>

			<!-- legend -->
			<div class="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted-foreground">
				{#each GAP_LEVELS as g (g.level)}
					<span class="flex items-center gap-1.5">
						<svg width="22" height="6" aria-hidden="true">
							<line x1="2" y1="3" x2="20" y2="3" stroke="var(--map-gap-{g.level})" stroke-width="2" stroke-dasharray={dash[g.level]} stroke-linecap="round" />
						</svg>
						<span class="text-foreground">{g.label}</span>
						{g.hint}
					</span>
				{/each}
				<span class="flex items-center gap-1.5">
					<svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="4" fill="var(--foreground)" /></svg>
					Confirmed
				</span>
				<span class="flex items-center gap-1.5">
					<svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="4" fill="none" stroke="var(--foreground)" stroke-width="1.5" /></svg>
					Unverified
				</span>
				<span class="flex items-center gap-1.5">
					<svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="5" fill="var(--map-gap-0)" /></svg>
					Latest
				</span>
			</div>
		{/if}
	</Card.Content>
</Card.Root>

<SnapshotDialog bind:open={dialogOpen} snapshot={selected} onUpdated={upsert} {onDeleted} />
