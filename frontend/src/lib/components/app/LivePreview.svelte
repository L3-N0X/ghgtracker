<script lang="ts">
	import MonitorIcon from '@lucide/svelte/icons/monitor';
	import * as Card from '$lib/components/ui/card';
	import { Label } from '$lib/components/ui/label';
	import { Switch } from '$lib/components/ui/switch';
	import { api } from '$lib/api/client';
	import type { TrackerStatus } from '$lib/api/types';
	import { cn } from '$lib/utils';

	let { streamerId, status }: { streamerId: number; status: TrackerStatus | undefined } = $props();

	let overlay = $state(true);
	let src = $state<string | null>(null);
	let objectUrl: string | null = null; // not reactive: only used to free the previous frame
	const running = $derived(status?.state === 'running');

	// Poll the latest analysed frame while the tracker runs (one request in flight at a time).
	$effect(() => {
		if (!running) return;
		const withOverlay = overlay;
		let cancelled = false;
		let timer: ReturnType<typeof setTimeout>;

		async function tick() {
			try {
				const res = await fetch(api.tracker.frameUrl(streamerId, withOverlay, Date.now()));
				if (!cancelled && res.status === 200) {
					const url = URL.createObjectURL(await res.blob());
					if (objectUrl) URL.revokeObjectURL(objectUrl);
					objectUrl = src = url;
				}
			} catch {
				// backend busy / restarting: try again next tick
			}
			if (!cancelled) timer = setTimeout(tick, 1000);
		}
		tick();
		return () => {
			cancelled = true;
			clearTimeout(timer);
		};
	});
</script>

<Card.Root class="overflow-hidden">
	<Card.Header>
		<Card.Title>Live preview</Card.Title>
		<Card.Description>The frame the detector analysed last, refreshed every second.</Card.Description>
		<Card.Action>
			<div class="flex items-center gap-2">
				<Switch id="overlay-{streamerId}" bind:checked={overlay} />
				<Label for="overlay-{streamerId}" class="text-xs font-normal text-muted-foreground">Detector overlay</Label>
			</div>
		</Card.Action>
	</Card.Header>
	<Card.Content>
		<div
			class={cn(
				'relative aspect-video overflow-hidden rounded-lg border bg-black',
				status?.f3_open && running && 'ring-2 ring-emerald-500',
			)}
		>
			{#if src}
				<img {src} alt="Latest analysed stream frame" class={cn('size-full object-contain', !running && 'opacity-40')} />
			{/if}
			{#if !src || !running}
				<div class="absolute inset-0 flex flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
					<MonitorIcon class="size-6" />
					{#if status?.state === 'starting'}
						Connecting to stream…
					{:else if !running}
						Preview appears while the tracker is running
					{:else}
						Waiting for first frame…
					{/if}
				</div>
			{/if}
		</div>
	</Card.Content>
</Card.Root>
