<script lang="ts">
	import { onMount } from 'svelte';
	import ImageIcon from '@lucide/svelte/icons/image';
	import ListIcon from '@lucide/svelte/icons/list';
	import * as Card from '$lib/components/ui/card';
	import * as Table from '$lib/components/ui/table';
	import * as Select from '$lib/components/ui/select';
	import * as Empty from '$lib/components/ui/empty';
	import { Button } from '$lib/components/ui/button';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { Spinner } from '$lib/components/ui/spinner';
	import OcrStatusBadge from './OcrStatusBadge.svelte';
	import SnapshotDialog from './SnapshotDialog.svelte';
	import { api } from '$lib/api/client';
	import type { Snapshot, TrackingSession } from '$lib/api/types';
	import { formatCoord, formatDateTime, formatDuration } from '$lib/format';
	import { live } from '$lib/stores/live.svelte';
	import { cn } from '$lib/utils';

	const PAGE_SIZE = 50;

	let { streamerId }: { streamerId: number } = $props();

	let items = $state<Snapshot[]>([]);
	let total = $state(0);
	let loading = $state(true);
	let loadingMore = $state(false);
	let sessions = $state<TrackingSession[]>([]);
	let sessionFilter = $state('all');
	let fresh = $state(new Set<number>());
	let selected = $state<Snapshot | null>(null);
	let dialogOpen = $state(false);

	const sessionId = $derived(sessionFilter === 'all' ? undefined : Number(sessionFilter));
	const sessionLabel = $derived(
		sessionFilter === 'all' ? 'All sessions' : `Session #${sessionFilter}`,
	);

	async function load(reset: boolean) {
		if (reset) loading = true;
		else loadingMore = true;
		try {
			const page = await api.snapshots.list({
				streamer_id: streamerId,
				session_id: sessionId,
				limit: PAGE_SIZE,
				offset: reset ? 0 : items.length,
			});
			items = reset ? page.items : [...items, ...page.items];
			total = page.total;
		} finally {
			loading = false;
			loadingMore = false;
		}
	}

	async function loadSessions() {
		sessions = await api.streamers.sessions(streamerId).catch(() => []);
	}

	$effect(() => {
		void sessionId;
		load(true);
	});

	onMount(() => {
		loadSessions();
		return live.subscribe((event) => {
			if (event.type === 'tracker.status' && event.status.streamer_id === streamerId) {
				if (event.status.session_id && !sessions.some((s) => s.id === event.status.session_id)) {
					loadSessions();
				}
			}
			if (event.type !== 'snapshot.created' || event.streamer_id !== streamerId) return;
			const snap = event.snapshot;
			if (sessionId !== undefined && snap.session_id !== sessionId) return;
			items = [snap, ...items];
			total += 1;
			fresh = new Set(fresh).add(snap.id);
			setTimeout(() => {
				const next = new Set(fresh);
				next.delete(snap.id);
				fresh = next;
			}, 2500);
		});
	});

	function open(snapshot: Snapshot) {
		selected = snapshot;
		dialogOpen = true;
	}

	function onUpdated(updated: Snapshot) {
		items = items.map((s) => (s.id === updated.id ? updated : s));
		selected = updated;
	}

	function onDeleted(id: number) {
		items = items.filter((s) => s.id !== id);
		total -= 1;
	}
</script>

<Card.Root>
	<Card.Header>
		<Card.Title>Coordinate log</Card.Title>
		<Card.Description>
			Every stored F3 snapshot. Coordinates and biome stay empty until OCR is added — open a row to
			view the frame or fill them in by hand.
		</Card.Description>
		<Card.Action>
			<Select.Root type="single" bind:value={sessionFilter}>
				<Select.Trigger size="sm" class="w-40">{sessionLabel}</Select.Trigger>
				<Select.Content>
					<Select.Item value="all" label="All sessions" />
					{#each sessions as session (session.id)}
						<Select.Item value={String(session.id)} label={`Session #${session.id}`}>
							<span>Session #{session.id}</span>
							<span class="ml-auto text-xs text-muted-foreground">{formatDateTime(session.started_at)}</span>
						</Select.Item>
					{/each}
				</Select.Content>
			</Select.Root>
		</Card.Action>
	</Card.Header>
	<Card.Content>
		{#if loading}
			<div class="space-y-2">
				{#each { length: 5 } as _, i (i)}<Skeleton class="h-9 w-full" />{/each}
			</div>
		{:else if items.length === 0}
			<Empty.Root class="border border-dashed py-10">
				<Empty.Header>
					<Empty.Media variant="icon"><ListIcon /></Empty.Media>
					<Empty.Title>No snapshots yet</Empty.Title>
					<Empty.Description>
						Snapshots appear here live as soon as the tracker sees the streamer open F3.
					</Empty.Description>
				</Empty.Header>
			</Empty.Root>
		{:else}
			<div class="overflow-x-auto">
				<Table.Root>
					<Table.Header>
						<Table.Row>
							<Table.Head>Captured</Table.Head>
							<Table.Head class="text-right">Stream time</Table.Head>
							<Table.Head class="text-right">X</Table.Head>
							<Table.Head class="text-right">Y</Table.Head>
							<Table.Head class="text-right">Z</Table.Head>
							<Table.Head>Biome</Table.Head>
							<Table.Head>Dimension</Table.Head>
							<Table.Head class="text-right">Conf.</Table.Head>
							<Table.Head>Status</Table.Head>
							<Table.Head class="w-10"><span class="sr-only">Image</span></Table.Head>
						</Table.Row>
					</Table.Header>
					<Table.Body>
						{#each items as snap (snap.id)}
							<Table.Row
								class={cn('cursor-pointer transition-colors duration-1000', fresh.has(snap.id) && 'bg-emerald-500/10')}
								onclick={() => open(snap)}
							>
								<Table.Cell class="whitespace-nowrap tabular-nums">{formatDateTime(snap.captured_at)}</Table.Cell>
								<Table.Cell class="text-right text-muted-foreground tabular-nums">
									{formatDuration(snap.stream_offset_seconds)}
								</Table.Cell>
								<Table.Cell class="text-right font-mono tabular-nums">{formatCoord(snap.x)}</Table.Cell>
								<Table.Cell class="text-right font-mono tabular-nums">{formatCoord(snap.y)}</Table.Cell>
								<Table.Cell class="text-right font-mono tabular-nums">{formatCoord(snap.z)}</Table.Cell>
								<Table.Cell class="max-w-48 truncate">{snap.biome?.replace('minecraft:', '') ?? '—'}</Table.Cell>
								<Table.Cell class="capitalize">{snap.dimension ?? '—'}</Table.Cell>
								<Table.Cell class="text-right tabular-nums">{snap.confidence.toFixed(2)}</Table.Cell>
								<Table.Cell><OcrStatusBadge status={snap.ocr_status} /></Table.Cell>
								<Table.Cell>
									{#if snap.image_url}
										<ImageIcon class="size-4 text-muted-foreground" aria-label="Has image" />
									{/if}
								</Table.Cell>
							</Table.Row>
						{/each}
					</Table.Body>
				</Table.Root>
			</div>
		{/if}
	</Card.Content>
	{#if !loading && items.length > 0}
		<Card.Footer class="justify-between text-sm text-muted-foreground">
			<span class="tabular-nums">Showing {items.length.toLocaleString()} of {total.toLocaleString()}</span>
			{#if items.length < total}
				<Button variant="outline" size="sm" disabled={loadingMore} onclick={() => load(false)}>
					{#if loadingMore}<Spinner />{/if}
					Load more
				</Button>
			{/if}
		</Card.Footer>
	{/if}
</Card.Root>

<SnapshotDialog bind:open={dialogOpen} snapshot={selected} {onUpdated} {onDeleted} />
