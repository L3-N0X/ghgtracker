<script lang="ts">
	import { onMount } from 'svelte';
	import ScanEyeIcon from '@lucide/svelte/icons/scan-eye';
	import * as Card from '$lib/components/ui/card';
	import * as Table from '$lib/components/ui/table';
	import * as Empty from '$lib/components/ui/empty';
	import { Badge } from '$lib/components/ui/badge';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { api } from '$lib/api/client';
	import type { F3Event } from '$lib/api/types';
	import { formatDateTime, formatDuration } from '$lib/format';
	import { live } from '$lib/stores/live.svelte';

	let { streamerId }: { streamerId: number } = $props();

	let items = $state<F3Event[]>([]);
	let total = $state(0);
	let loading = $state(true);

	async function load() {
		try {
			const page = await api.f3Events.list({ streamer_id: streamerId, limit: 100 });
			items = page.items;
			total = page.total;
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		load();
		return live.subscribe((event) => {
			if ((event.type === 'f3.opened' || event.type === 'f3.closed') && event.streamer_id === streamerId) {
				load();
			}
		});
	});
</script>

<Card.Root>
	<Card.Header>
		<Card.Title>F3 openings</Card.Title>
		<Card.Description>
			Each continuous period the debug screen was visible, even single frames. {total.toLocaleString()} total.
		</Card.Description>
	</Card.Header>
	<Card.Content>
		{#if loading}
			<div class="space-y-2">
				{#each { length: 4 } as _, i (i)}<Skeleton class="h-9 w-full" />{/each}
			</div>
		{:else if items.length === 0}
			<Empty.Root class="border border-dashed py-10">
				<Empty.Header>
					<Empty.Media variant="icon"><ScanEyeIcon /></Empty.Media>
					<Empty.Title>No F3 openings detected yet</Empty.Title>
				</Empty.Header>
			</Empty.Root>
		{:else}
			<Table.Root>
				<Table.Header>
					<Table.Row>
						<Table.Head>Opened</Table.Head>
						<Table.Head class="text-right">Duration</Table.Head>
						<Table.Head class="text-right">Frames</Table.Head>
						<Table.Head class="text-right">Peak conf.</Table.Head>
						<Table.Head class="text-right">Session</Table.Head>
					</Table.Row>
				</Table.Header>
				<Table.Body>
					{#each items as event (event.id)}
						<Table.Row>
							<Table.Cell class="tabular-nums">{formatDateTime(event.opened_at)}</Table.Cell>
							<Table.Cell class="text-right tabular-nums">
								{#if event.closed_at}
									{formatDuration(event.duration_seconds)}
								{:else}
									<Badge variant="outline" class="text-emerald-400">open</Badge>
								{/if}
							</Table.Cell>
							<!-- Frame count / peak are written when the opening ends. -->
							<Table.Cell class="text-right tabular-nums">{event.closed_at ? event.frame_count : '—'}</Table.Cell>
							<Table.Cell class="text-right tabular-nums">
								{event.closed_at ? event.peak_confidence.toFixed(2) : '—'}
							</Table.Cell>
							<Table.Cell class="text-right text-muted-foreground tabular-nums">#{event.session_id}</Table.Cell>
						</Table.Row>
					{/each}
				</Table.Body>
			</Table.Root>
		{/if}
	</Card.Content>
</Card.Root>
