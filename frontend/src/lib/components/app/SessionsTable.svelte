<script lang="ts">
	import { onMount } from 'svelte';
	import HistoryIcon from '@lucide/svelte/icons/history';
	import * as Card from '$lib/components/ui/card';
	import * as Table from '$lib/components/ui/table';
	import * as Empty from '$lib/components/ui/empty';
	import * as Tooltip from '$lib/components/ui/tooltip';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import TrackerStateBadge from './TrackerStateBadge.svelte';
	import { api } from '$lib/api/client';
	import type { TrackerState, TrackingSession } from '$lib/api/types';
	import { formatDateTime, formatDuration, formatNumber } from '$lib/format';
	import { live } from '$lib/stores/live.svelte';

	let { streamerId }: { streamerId: number } = $props();

	let items = $state<TrackingSession[]>([]);
	let loading = $state(true);
	let lastState: TrackerState | undefined;

	async function load() {
		try {
			items = await api.streamers.sessions(streamerId);
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		load();
		return live.subscribe((event) => {
			if (event.type !== 'tracker.status' || event.status.streamer_id !== streamerId) return;
			if (event.status.state !== lastState) load();
			lastState = event.status.state;
		});
	});

	function duration(s: TrackingSession) {
		const end = s.ended_at ? new Date(s.ended_at).getTime() : Date.now();
		return formatDuration((end - new Date(s.started_at).getTime()) / 1000);
	}

	const stateOf = (s: TrackingSession): TrackerState => (s.status === 'running' ? 'running' : s.status);
</script>

<Card.Root>
	<Card.Header>
		<Card.Title>Tracking sessions</Card.Title>
		<Card.Description>One session per tracker start. Counters are flushed every few seconds.</Card.Description>
	</Card.Header>
	<Card.Content>
		{#if loading}
			<div class="space-y-2">
				{#each { length: 3 } as _, i (i)}<Skeleton class="h-9 w-full" />{/each}
			</div>
		{:else if items.length === 0}
			<Empty.Root class="border border-dashed py-10">
				<Empty.Header>
					<Empty.Media variant="icon"><HistoryIcon /></Empty.Media>
					<Empty.Title>No sessions yet</Empty.Title>
				</Empty.Header>
			</Empty.Root>
		{:else}
			<div class="overflow-x-auto">
				<Table.Root>
					<Table.Header>
						<Table.Row>
							<Table.Head>#</Table.Head>
							<Table.Head>Started</Table.Head>
							<Table.Head class="text-right">Duration</Table.Head>
							<Table.Head>Status</Table.Head>
							<Table.Head class="text-right">Frames</Table.Head>
							<Table.Head class="text-right">F3 openings</Table.Head>
							<Table.Head class="text-right">Snapshots</Table.Head>
							<Table.Head>Source</Table.Head>
						</Table.Row>
					</Table.Header>
					<Table.Body>
						{#each items as s (s.id)}
							<Table.Row>
								<Table.Cell class="text-muted-foreground tabular-nums">{s.id}</Table.Cell>
								<Table.Cell class="whitespace-nowrap tabular-nums">{formatDateTime(s.started_at)}</Table.Cell>
								<Table.Cell class="text-right tabular-nums">{duration(s)}</Table.Cell>
								<Table.Cell>
									{#if s.error}
										<Tooltip.Root>
											<Tooltip.Trigger><TrackerStateBadge state={stateOf(s)} /></Tooltip.Trigger>
											<Tooltip.Content>{s.error}</Tooltip.Content>
										</Tooltip.Root>
									{:else}
										<TrackerStateBadge state={stateOf(s)} />
									{/if}
								</Table.Cell>
								<Table.Cell class="text-right tabular-nums">{formatNumber(s.frames_processed)}</Table.Cell>
								<Table.Cell class="text-right tabular-nums">{formatNumber(s.f3_events)}</Table.Cell>
								<Table.Cell class="text-right tabular-nums">{formatNumber(s.snapshots_saved)}</Table.Cell>
								<Table.Cell class="max-w-64 truncate text-muted-foreground" title={s.source}>{s.source}</Table.Cell>
							</Table.Row>
						{/each}
					</Table.Body>
				</Table.Root>
			</div>
		{/if}
	</Card.Content>
</Card.Root>
