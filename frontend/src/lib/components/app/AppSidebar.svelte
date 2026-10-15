<script lang="ts">
	import PlusIcon from '@lucide/svelte/icons/plus';
	import FlaskConicalIcon from '@lucide/svelte/icons/flask-conical';
	import CrosshairIcon from '@lucide/svelte/icons/crosshair';
	import { Button } from '$lib/components/ui/button';
	import { Separator } from '$lib/components/ui/separator';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { ScrollArea } from '$lib/components/ui/scroll-area';
	import AddStreamerDialog from './AddStreamerDialog.svelte';
	import TrackerStateBadge from './TrackerStateBadge.svelte';
	import { live } from '$lib/stores/live.svelte';
	import { streamerName, streamers } from '$lib/stores/streamers.svelte';
	import { router } from '$lib/stores/router.svelte';
	import { cn } from '$lib/utils';

	let addOpen = $state(false);
	const activeId = $derived(router.route.name === 'streamer' ? router.route.id : null);
</script>

<aside class="flex w-72 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground">
	<a href="#/" class="flex items-center gap-2.5 px-4 py-4">
		<div class="flex size-8 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400">
			<CrosshairIcon class="size-4.5" />
		</div>
		<div class="leading-tight">
			<div class="text-sm font-semibold">GHG Tracker</div>
			<div class="text-xs text-muted-foreground">Minecraft F3 coordinate tracker</div>
		</div>
	</a>
	<Separator />

	<div class="flex items-center justify-between px-4 pt-4 pb-2">
		<span class="text-xs font-medium tracking-wide text-muted-foreground uppercase">Streamers</span>
		<Button variant="ghost" size="icon-sm" aria-label="Add streamer" onclick={() => (addOpen = true)}>
			<PlusIcon />
		</Button>
	</div>

	<ScrollArea class="min-h-0 flex-1">
		<nav class="flex flex-col gap-0.5 px-2 pb-2">
			{#if streamers.loading && streamers.items.length === 0}
				{#each { length: 3 } as _, i (i)}
					<div class="flex items-center gap-3 px-2 py-2">
						<Skeleton class="size-8 rounded-full" />
						<div class="flex-1 space-y-1.5">
							<Skeleton class="h-3 w-24" />
							<Skeleton class="h-2.5 w-16" />
						</div>
					</div>
				{/each}
			{:else if streamers.error}
				<p class="px-2 py-3 text-sm text-destructive">Backend unreachable: {streamers.error}</p>
			{:else if streamers.items.length === 0}
				<p class="px-2 py-3 text-sm text-muted-foreground">
					No streamers yet. Add one to start tracking.
				</p>
			{/if}

			{#each streamers.items as streamer (streamer.id)}
				{@const status = live.tracker(streamer.id)}
				<a
					href="#/streamers/{streamer.id}"
					class={cn(
						'group flex items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-sidebar-accent',
						activeId === streamer.id && 'bg-sidebar-accent',
					)}
				>
					<div
						class={cn(
							'relative flex size-8 shrink-0 items-center justify-center rounded-full bg-muted text-sm font-semibold uppercase',
							status?.f3_open && 'ring-2 ring-emerald-400',
						)}
					>
						{streamerName(streamer).charAt(0)}
					</div>
					<div class="min-w-0 flex-1">
						<div class="truncate text-sm font-medium">{streamerName(streamer)}</div>
						<div class="truncate text-xs text-muted-foreground">
							{streamer.snapshot_count.toLocaleString()} snapshots
						</div>
					</div>
					{#if status && status.state !== 'idle'}
						<TrackerStateBadge state={status.state} compact />
					{/if}
				</a>
			{/each}
		</nav>
	</ScrollArea>

	<Separator />
	<div class="flex flex-col gap-1 p-2">
		<Button
			variant="ghost"
			class={cn('justify-start', router.route.name === 'lab' && 'bg-sidebar-accent')}
			href="#/lab"
		>
			<FlaskConicalIcon />
			Detector lab
		</Button>
		<div class="flex items-center gap-2 px-2.5 py-1.5 text-xs text-muted-foreground">
			<span
				class={cn('size-2 rounded-full', live.connected ? 'bg-emerald-500' : 'bg-amber-500 animate-pulse')}
			></span>
			{live.connected ? 'Live updates connected' : 'Connecting to backend…'}
		</div>
	</div>
</aside>

<AddStreamerDialog bind:open={addOpen} />
