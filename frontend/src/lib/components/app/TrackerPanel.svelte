<script lang="ts">
	import { toast } from 'svelte-sonner';
	import PlayIcon from '@lucide/svelte/icons/play';
	import SquareIcon from '@lucide/svelte/icons/square';
	import EyeIcon from '@lucide/svelte/icons/eye';
	import EyeOffIcon from '@lucide/svelte/icons/eye-off';
	import TriangleAlertIcon from '@lucide/svelte/icons/triangle-alert';
	import * as Card from '$lib/components/ui/card';
	import * as Alert from '$lib/components/ui/alert';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { Switch } from '$lib/components/ui/switch';
	import { Spinner } from '$lib/components/ui/spinner';
	import TrackerStateBadge from './TrackerStateBadge.svelte';
	import { api } from '$lib/api/client';
	import type { Streamer, TrackerStatus } from '$lib/api/types';
	import { formatRelative } from '$lib/format';
	import { live } from '$lib/stores/live.svelte';
	import { now } from '$lib/stores/clock.svelte';
	import { cn } from '$lib/utils';

	let { streamer, status }: { streamer: Streamer; status: TrackerStatus | undefined } = $props();

	// Tracker settings are remembered per streamer in this browser.
	const storageKey = $derived(`ghg.tracker-settings.${streamer.id}`);
	const defaults = { source: '', fps: 15, interval: 5, saveImages: true };
	let settings = $state({ ...defaults });
	let busy = $state(false);

	$effect(() => {
		try {
			const stored = localStorage.getItem(storageKey);
			settings = stored ? { ...defaults, ...JSON.parse(stored) } : { ...defaults };
		} catch {
			settings = { ...defaults };
		}
	});

	const trackerState = $derived(status?.state ?? 'idle');
	const active = $derived(trackerState === 'starting' || trackerState === 'running' || trackerState === 'stopping');
	const f3Open = $derived(trackerState === 'running' && !!status?.f3_open);

	async function start() {
		busy = true;
		try {
			try {
				localStorage.setItem(storageKey, JSON.stringify(settings));
			} catch {
				// storage unavailable: settings just won't be remembered
			}
			const result = await api.tracker.start(streamer.id, {
				source: settings.source.trim() || null,
				capture_fps: settings.fps,
				save_interval_seconds: settings.interval,
				save_images: settings.saveImages,
			});
			live.setStatus(result);
		} catch (err) {
			toast.error('Could not start tracker', {
				description: err instanceof Error ? err.message : String(err),
			});
		} finally {
			busy = false;
		}
	}

	async function stop() {
		busy = true;
		try {
			live.setStatus(await api.tracker.stop(streamer.id));
		} catch (err) {
			toast.error(err instanceof Error ? err.message : String(err));
		} finally {
			busy = false;
		}
	}
</script>

<Card.Root>
	<Card.Header>
		<Card.Title>Tracker</Card.Title>
		<Card.Description>Detects the F3 screen on every captured frame.</Card.Description>
		<Card.Action><TrackerStateBadge state={trackerState} /></Card.Action>
	</Card.Header>

	<Card.Content class="flex flex-col gap-5">
		<!-- F3 indicator -->
		<div
			class={cn(
				'flex items-center gap-3 rounded-xl border px-4 py-3 transition-colors duration-150',
				f3Open ? 'border-emerald-500/60 bg-emerald-500/10' : 'bg-muted/40',
			)}
			aria-live="polite"
		>
			<div
				class={cn(
					'flex size-10 items-center justify-center rounded-lg font-mono text-sm font-bold',
					f3Open ? 'bg-emerald-500 text-emerald-950' : 'bg-muted text-muted-foreground',
				)}
			>
				F3
			</div>
			<div class="min-w-0 flex-1">
				<div class="flex items-center gap-1.5 text-sm font-medium">
					{#if f3Open}
						<EyeIcon class="size-4 text-emerald-400" /> Debug screen open
					{:else}
						<EyeOffIcon class="size-4 text-muted-foreground" /> Debug screen closed
					{/if}
				</div>
				<div class="text-xs text-muted-foreground tabular-nums">
					{#if active}
						confidence {(status?.last_confidence ?? 0).toFixed(2)} · last seen
						{formatRelative(status?.last_f3_at, now.current)}
					{:else}
						Start the tracker to watch the stream
					{/if}
				</div>
			</div>
		</div>

		{#if trackerState === 'error' && status?.error}
			<Alert.Root variant="destructive">
				<TriangleAlertIcon />
				<Alert.Title>Tracker stopped</Alert.Title>
				<Alert.Description>{status.error}</Alert.Description>
			</Alert.Root>
		{/if}

		<fieldset class="grid gap-4" disabled={active}>
			<div class="grid gap-2">
				<Label for="source">Source</Label>
				<Input
					id="source"
					placeholder="Live channel (default)"
					bind:value={settings.source}
				/>
				<p class="text-xs text-muted-foreground">
					Leave empty for twitch.tv/{streamer.login}. A VOD URL or a local video path works for testing.
				</p>
			</div>
			<div class="grid grid-cols-2 gap-3">
				<div class="grid gap-2">
					<Label for="fps">Analysis fps</Label>
					<Input id="fps" type="number" min="1" max="60" step="1" bind:value={settings.fps} />
				</div>
				<div class="grid gap-2">
					<Label for="interval">Snapshot every (s)</Label>
					<Input id="interval" type="number" min="0" step="0.5" bind:value={settings.interval} />
				</div>
			</div>
			<div class="flex items-center justify-between gap-3">
				<Label for="save-images" class="flex-col items-start gap-0.5">
					<span>Store snapshot images</span>
					<span class="text-xs font-normal text-muted-foreground">Needed for OCR later</span>
				</Label>
				<Switch id="save-images" bind:checked={settings.saveImages} />
			</div>
		</fieldset>
	</Card.Content>

	<Card.Footer>
		{#if active}
			<Button class="w-full" variant="destructive" disabled={busy || trackerState === 'stopping'} onclick={stop}>
				{#if busy || trackerState === 'stopping'}<Spinner />{:else}<SquareIcon />{/if}
				Stop tracker
			</Button>
		{:else}
			<Button class="w-full" disabled={busy} onclick={start}>
				{#if busy}<Spinner />{:else}<PlayIcon />{/if}
				Start tracker
			</Button>
		{/if}
	</Card.Footer>
</Card.Root>
