<script lang="ts">
	import UsersIcon from '@lucide/svelte/icons/users';
	import PlusIcon from '@lucide/svelte/icons/plus';
	import ScanEyeIcon from '@lucide/svelte/icons/scan-eye';
	import DatabaseIcon from '@lucide/svelte/icons/database';
	import RadioIcon from '@lucide/svelte/icons/radio';
	import MapIcon from '@lucide/svelte/icons/map';
	import * as Empty from '$lib/components/ui/empty';
	import { Button } from '$lib/components/ui/button';
	import AddStreamerDialog from './AddStreamerDialog.svelte';
	import { streamers } from '$lib/stores/streamers.svelte';

	let addOpen = $state(false);

	const steps = [
		{
			icon: RadioIcon,
			title: 'Capture',
			text: 'streamlink pulls the live stream, ffmpeg decodes it at a fixed frame rate.',
		},
		{
			icon: ScanEyeIcon,
			title: 'Detect F3',
			text: 'Every frame is checked for the debug overlay, so even short openings are caught.',
		},
		{
			icon: DatabaseIcon,
			title: 'Snapshot',
			text: 'While F3 is open a snapshot is stored every few seconds for coordinate reading.',
		},
		{
			icon: MapIcon,
			title: 'Coming next',
			text: 'OCR for XYZ / biome, then the walking path on a map.',
		},
	];
</script>

<div class="mx-auto flex min-h-full max-w-3xl flex-col justify-center gap-10 p-8">
	<Empty.Root class="border-0">
		<Empty.Header>
			<Empty.Media variant="icon"><UsersIcon /></Empty.Media>
			<Empty.Title>
				{streamers.items.length ? 'Select a streamer' : 'Add your first streamer'}
			</Empty.Title>
			<Empty.Description>
				{streamers.items.length
					? 'Pick a streamer from the sidebar to start the tracker and browse their coordinate log.'
					: 'Add a Twitch channel, then start the tracker while they are live.'}
			</Empty.Description>
		</Empty.Header>
		<Empty.Content>
			<Button onclick={() => (addOpen = true)}><PlusIcon /> Add streamer</Button>
		</Empty.Content>
	</Empty.Root>

	<ol class="grid gap-3 sm:grid-cols-2">
		{#each steps as step, i (step.title)}
			<li class="flex gap-3 rounded-xl border bg-card p-4">
				<div class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
					<step.icon class="size-4" />
				</div>
				<div>
					<div class="text-sm font-medium">{i + 1}. {step.title}</div>
					<p class="text-sm text-muted-foreground">{step.text}</p>
				</div>
			</li>
		{/each}
	</ol>
</div>

<AddStreamerDialog bind:open={addOpen} />
