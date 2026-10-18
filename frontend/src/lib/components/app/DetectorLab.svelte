<script lang="ts">
	import { onMount } from 'svelte';
	import UploadIcon from '@lucide/svelte/icons/upload';
	import CheckIcon from '@lucide/svelte/icons/circle-check';
	import XIcon from '@lucide/svelte/icons/circle-x';
	import ScanTextIcon from '@lucide/svelte/icons/scan-text';
	import * as Card from '$lib/components/ui/card';
	import { Spinner } from '$lib/components/ui/spinner';
	import { api } from '$lib/api/client';
	import type { DetectionResult, OcrInfo } from '$lib/api/types';
	import OcrStatusBadge from './OcrStatusBadge.svelte';
	import { formatCoord } from '$lib/format';
	import { cn } from '$lib/utils';

	let result = $state<DetectionResult | null>(null);
	let fileName = $state<string | null>(null);
	let busy = $state(false);
	let error = $state<string | null>(null);
	let dragging = $state(false);
	let ocrInfo = $state<OcrInfo | null>(null);
	let input: HTMLInputElement;

	async function analyse(file: File) {
		busy = true;
		error = null;
		fileName = file.name || 'pasted image';
		try {
			result = await api.detect(file);
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
			result = null;
		} finally {
			busy = false;
		}
	}

	function onDrop(event: DragEvent) {
		event.preventDefault();
		dragging = false;
		const file = event.dataTransfer?.files[0];
		if (file) analyse(file);
	}

	onMount(() => {
		api.ocr
			.info()
			.then((info) => (ocrInfo = info))
			.catch(() => {});
		const onPaste = (event: ClipboardEvent) => {
			const file = [...(event.clipboardData?.files ?? [])].find((f) => f.type.startsWith('image/'));
			if (file) analyse(file);
		};
		window.addEventListener('paste', onPaste);
		return () => window.removeEventListener('paste', onPaste);
	});

	const metrics = $derived(
		result
			? [
					{ label: 'Confidence', value: result.confidence.toFixed(3) },
					{ label: 'Left column lines', value: String(result.left.line_count) },
					{ label: 'Right column lines', value: String(result.right.line_count) },
					{ label: 'GUI scale', value: result.gui_scale?.toFixed(2) ?? '—' },
					{ label: 'Line pitch (px)', value: (result.left.pitch ?? result.right.pitch)?.toFixed(1) ?? '—' },
					{
						label: 'Pixel grid (L / R)',
						value: `${result.left.grid.toFixed(2)} / ${result.right.grid.toFixed(2)}`,
					},
					{ label: 'Detection time', value: `${result.elapsed_ms.toFixed(1)} ms` },
				]
			: [],
	);

	const reading = $derived(result?.ocr ?? null);
	const readingRows = $derived(
		reading
			? [
					{ label: 'X', value: formatCoord(reading.x, 3), mono: true },
					{ label: 'Y', value: formatCoord(reading.y, 3), mono: true },
					{ label: 'Z', value: formatCoord(reading.z, 3), mono: true },
					{ label: 'Dimension', value: reading.dimension ?? '—', mono: false },
					{ label: 'Biome', value: reading.biome?.replace('minecraft:', '') ?? '—', mono: false },
					{ label: 'Facing', value: reading.facing ?? '—', mono: false },
					{ label: 'OCR time', value: `${reading.elapsed_ms.toFixed(0)} ms`, mono: false },
				]
			: [],
	);
	const ocrUnavailable = $derived(
		!ocrInfo || ocrInfo.state === 'off'
			? 'OCR is switched off (GHG_OCR_ENGINE=none).'
			: ocrInfo.state === 'error'
				? `OCR engine failed to load: ${ocrInfo.error}`
				: null,
	);
</script>

<div class="mx-auto flex max-w-6xl flex-col gap-6 p-6">
	<header>
		<h1 class="text-xl font-semibold tracking-tight">Detector lab</h1>
		<p class="text-sm text-muted-foreground">
			Test the F3 detector and OCR on a screenshot. Drop, choose or paste (Ctrl+V) an image — the
			detected debug-text lines are boxed in the result, and the values OCR reads are listed.
		</p>
	</header>

	<button
		type="button"
		class={cn(
			'flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-sm text-muted-foreground transition-colors hover:border-ring hover:text-foreground',
			dragging && 'border-ring bg-muted/50 text-foreground',
		)}
		onclick={() => input.click()}
		ondragover={(e) => {
			e.preventDefault();
			dragging = true;
		}}
		ondragleave={() => (dragging = false)}
		ondrop={onDrop}
	>
		{#if busy}
			<Spinner class="size-6" />
			Analysing {fileName}…
		{:else}
			<UploadIcon class="size-6" />
			<span><span class="font-medium text-foreground">Choose a screenshot</span> or drop it here</span>
		{/if}
	</button>
	<input
		bind:this={input}
		type="file"
		accept="image/*"
		class="hidden"
		onchange={(e) => {
			const file = e.currentTarget.files?.[0];
			if (file) analyse(file);
			e.currentTarget.value = '';
		}}
	/>

	{#if error}
		<p class="text-sm text-destructive">{error}</p>
	{/if}

	{#if result}
		<div class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
			<Card.Root class="overflow-hidden">
				<Card.Content>
					<img src={result.overlay_jpeg} alt="Detector overlay for {fileName}" class="w-full rounded-lg border" />
				</Card.Content>
			</Card.Root>
			<div class="flex flex-col gap-6">
				<Card.Root>
					<Card.Header>
						<Card.Title class="flex items-center gap-2">
							{#if result.detected}
								<CheckIcon class="size-5 text-emerald-400" /> F3 detected
							{:else}
								<XIcon class="size-5 text-muted-foreground" /> No F3 screen
							{/if}
						</Card.Title>
						<Card.Description class="truncate">{fileName} · {result.width}×{result.height}</Card.Description>
					</Card.Header>
					<Card.Content>
						<dl class="grid gap-3">
							{#each metrics as m (m.label)}
								<div class="flex items-baseline justify-between gap-3 border-b pb-2 last:border-0">
									<dt class="text-sm text-muted-foreground">{m.label}</dt>
									<dd class="font-medium tabular-nums">{m.value}</dd>
								</div>
							{/each}
						</dl>
					</Card.Content>
				</Card.Root>
				{#if result.detected}
					<Card.Root>
						<Card.Header>
							<Card.Title class="flex items-center gap-2">
								<ScanTextIcon class="size-5 text-muted-foreground" /> OCR
							</Card.Title>
							{#if reading}
								<Card.Description>{reading.engine}</Card.Description>
								<Card.Action>
									<OcrStatusBadge
										status={reading.x === null ? 'failed' : reading.confirmed ? 'done' : 'unverified'}
									/>
								</Card.Action>
							{/if}
						</Card.Header>
						<Card.Content>
							{#if reading}
								<dl class="grid gap-3">
									{#each readingRows as row (row.label)}
										<div class="flex items-baseline justify-between gap-3 border-b pb-2 last:border-0">
											<dt class="text-sm text-muted-foreground">{row.label}</dt>
											<dd class={cn('truncate font-medium tabular-nums', row.mono && 'font-mono')}>{row.value}</dd>
										</div>
									{/each}
								</dl>
								{#if reading.raw_text}
									<details class="mt-3 text-sm">
										<summary class="cursor-pointer text-muted-foreground">OCR text</summary>
										<pre class="mt-2 max-h-64 overflow-auto rounded-md border bg-muted/40 p-2 font-mono text-xs whitespace-pre-wrap">{reading.raw_text}</pre>
									</details>
								{/if}
							{:else}
								<p class="text-sm text-muted-foreground">
									{ocrUnavailable ?? 'OCR could not read this screenshot.'}
								</p>
							{/if}
						</Card.Content>
					</Card.Root>
				{/if}
			</div>
		</div>
	{/if}
</div>
