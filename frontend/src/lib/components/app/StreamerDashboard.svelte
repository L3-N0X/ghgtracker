<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import Trash2Icon from '@lucide/svelte/icons/trash-2';
	import WifiIcon from '@lucide/svelte/icons/wifi';
	import WifiOffIcon from '@lucide/svelte/icons/wifi-off';
	import RefreshCwIcon from '@lucide/svelte/icons/refresh-cw';
	import * as Tabs from '$lib/components/ui/tabs';
	import * as Empty from '$lib/components/ui/empty';
	import { Badge } from '$lib/components/ui/badge';
	import { Button } from '$lib/components/ui/button';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { Spinner } from '$lib/components/ui/spinner';
	import TrackerPanel from './TrackerPanel.svelte';
	import LivePreview from './LivePreview.svelte';
	import TrackerStats from './TrackerStats.svelte';
	import CoordinateLog from './CoordinateLog.svelte';
	import F3EventsTable from './F3EventsTable.svelte';
	import SessionsTable from './SessionsTable.svelte';
	import ConfirmDialog from './ConfirmDialog.svelte';
	import { api } from '$lib/api/client';
	import { live } from '$lib/stores/live.svelte';
	import { streamerName, streamers } from '$lib/stores/streamers.svelte';
	import { router } from '$lib/stores/router.svelte';

	let { streamerId }: { streamerId: number } = $props();

	const streamer = $derived(streamers.byId(streamerId));
	const status = $derived(live.tracker(streamerId));

	let liveState = $state<'unknown' | 'checking' | 'live' | 'offline'>('unknown');
	let confirmDelete = $state(false);
	let tab = $state('log');

	onMount(() => {
		api.tracker
			.status(streamerId)
			.then((s) => live.setStatus(s))
			.catch(() => {});
		checkLive();
	});

	async function checkLive() {
		liveState = 'checking';
		try {
			liveState = (await api.streamers.live(streamerId)).live ? 'live' : 'offline';
		} catch {
			liveState = 'unknown';
		}
	}

	async function remove() {
		if (!streamer) return;
		try {
			await streamers.remove(streamer.id);
			toast.success(`Removed ${streamerName(streamer)}`);
			router.go('/');
		} catch (err) {
			toast.error(err instanceof Error ? err.message : String(err));
		}
	}
</script>

{#if !streamer}
	{#if streamers.loading}
		<div class="space-y-4 p-6">
			<Skeleton class="h-8 w-56" />
			<Skeleton class="h-64 w-full" />
		</div>
	{:else}
		<Empty.Root class="h-full">
			<Empty.Header>
				<Empty.Title>Streamer not found</Empty.Title>
				<Empty.Description>It may have been removed.</Empty.Description>
			</Empty.Header>
			<Empty.Content><Button href="#/" variant="outline">Back</Button></Empty.Content>
		</Empty.Root>
	{/if}
{:else}
	<div class="mx-auto flex max-w-7xl flex-col gap-6 p-6">
		<header class="flex flex-wrap items-center gap-x-4 gap-y-2">
			<div class="flex size-11 items-center justify-center rounded-full bg-muted text-lg font-semibold uppercase">
				{streamerName(streamer).charAt(0)}
			</div>
			<div class="min-w-0">
				<h1 class="truncate text-xl font-semibold tracking-tight">{streamerName(streamer)}</h1>
				<a
					href="https://www.twitch.tv/{streamer.login}"
					target="_blank"
					rel="noreferrer"
					class="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
				>
					twitch.tv/{streamer.login}
					<ExternalLinkIcon class="size-3" />
				</a>
			</div>
			<button
				type="button"
				onclick={checkLive}
				title="Check again"
				class="ml-1 rounded-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
			>
				{#if liveState === 'checking'}
					<Badge variant="outline" class="gap-1"><Spinner class="size-3" /> Checking</Badge>
				{:else if liveState === 'live'}
					<Badge variant="outline" class="gap-1 text-red-400"><WifiIcon /> Live now</Badge>
				{:else if liveState === 'offline'}
					<Badge variant="outline" class="gap-1 text-muted-foreground"><WifiOffIcon /> Offline</Badge>
				{:else}
					<Badge variant="outline" class="gap-1 text-muted-foreground"><RefreshCwIcon /> Live status</Badge>
				{/if}
			</button>
			<div class="ml-auto">
				<Button variant="ghost" size="sm" class="text-muted-foreground" onclick={() => (confirmDelete = true)}>
					<Trash2Icon />
					Remove
				</Button>
			</div>
		</header>

		<TrackerStats {status} />

		<div class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
			<LivePreview {streamerId} {status} />
			<TrackerPanel {streamer} {status} />
		</div>

		<Tabs.Root bind:value={tab}>
			<Tabs.List>
				<Tabs.Trigger value="log">Coordinate log</Tabs.Trigger>
				<Tabs.Trigger value="events">F3 openings</Tabs.Trigger>
				<Tabs.Trigger value="sessions">Sessions</Tabs.Trigger>
			</Tabs.List>
			<Tabs.Content value="log" class="pt-2">
				<CoordinateLog {streamerId} />
			</Tabs.Content>
			<Tabs.Content value="events" class="pt-2">
				<F3EventsTable {streamerId} />
			</Tabs.Content>
			<Tabs.Content value="sessions" class="pt-2">
				<SessionsTable {streamerId} />
			</Tabs.Content>
		</Tabs.Root>
	</div>

	<ConfirmDialog
		bind:open={confirmDelete}
		title="Remove {streamerName(streamer)}?"
		description="This stops a running tracker and permanently deletes all sessions, F3 openings and snapshots (including images) for this streamer."
		confirmLabel="Remove streamer"
		destructive
		onConfirm={remove}
	/>
{/if}
