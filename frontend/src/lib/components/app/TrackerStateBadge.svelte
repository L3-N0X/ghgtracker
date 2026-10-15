<script lang="ts">
	import CircleDotIcon from '@lucide/svelte/icons/circle-dot';
	import CircleStopIcon from '@lucide/svelte/icons/circle-stop';
	import LoaderIcon from '@lucide/svelte/icons/loader-circle';
	import TriangleAlertIcon from '@lucide/svelte/icons/triangle-alert';
	import CircleIcon from '@lucide/svelte/icons/circle';
	import { Badge } from '$lib/components/ui/badge';
	import type { TrackerState } from '$lib/api/types';
	import { cn } from '$lib/utils';

	let { state, compact = false }: { state: TrackerState; compact?: boolean } = $props();

	const config = $derived(
		{
			idle: { label: 'Idle', icon: CircleIcon, class: 'text-muted-foreground' },
			starting: { label: 'Starting', icon: LoaderIcon, class: 'text-sky-400 [&_svg]:animate-spin' },
			running: { label: 'Tracking', icon: CircleDotIcon, class: 'text-emerald-400 [&_svg]:animate-pulse' },
			stopping: { label: 'Stopping', icon: LoaderIcon, class: 'text-amber-400 [&_svg]:animate-spin' },
			stopped: { label: 'Stopped', icon: CircleStopIcon, class: 'text-muted-foreground' },
			error: { label: 'Error', icon: TriangleAlertIcon, class: 'text-red-400' },
		}[state],
	);
</script>

{#if compact}
	<span class={cn('flex items-center', config.class)} title={config.label}>
		<config.icon class="size-3.5" />
		<span class="sr-only">{config.label}</span>
	</span>
{:else}
	<Badge variant="outline" class={cn('gap-1', config.class)}>
		<config.icon />
		{config.label}
	</Badge>
{/if}
