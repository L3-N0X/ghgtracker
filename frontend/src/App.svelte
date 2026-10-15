<script lang="ts">
	import { onMount } from 'svelte';
	import { ModeWatcher } from 'mode-watcher';
	import { Toaster } from '$lib/components/ui/sonner';
	import * as Tooltip from '$lib/components/ui/tooltip';
	import AppSidebar from '$lib/components/app/AppSidebar.svelte';
	import HomeView from '$lib/components/app/HomeView.svelte';
	import StreamerDashboard from '$lib/components/app/StreamerDashboard.svelte';
	import DetectorLab from '$lib/components/app/DetectorLab.svelte';
	import { live } from '$lib/stores/live.svelte';
	import { streamers } from '$lib/stores/streamers.svelte';
	import { router } from '$lib/stores/router.svelte';

	onMount(() => {
		live.start();
		streamers.load();
	});
</script>

<ModeWatcher defaultMode="dark" />
<Toaster richColors position="bottom-right" />

<Tooltip.Provider delayDuration={200}>
	<div class="flex h-svh overflow-hidden bg-background text-foreground">
		<AppSidebar />
		<main class="min-w-0 flex-1 overflow-y-auto">
			{#if router.route.name === 'streamer'}
				{#key router.route.id}
					<StreamerDashboard streamerId={router.route.id} />
				{/key}
			{:else if router.route.name === 'lab'}
				<DetectorLab />
			{:else}
				<HomeView />
			{/if}
		</main>
	</div>
</Tooltip.Provider>
