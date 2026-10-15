<script lang="ts">
	import { toast } from 'svelte-sonner';
	import Trash2Icon from '@lucide/svelte/icons/trash-2';
	import ImageOffIcon from '@lucide/svelte/icons/image-off';
	import * as Dialog from '$lib/components/ui/dialog';
	import * as Select from '$lib/components/ui/select';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { Spinner } from '$lib/components/ui/spinner';
	import OcrStatusBadge from './OcrStatusBadge.svelte';
	import { api } from '$lib/api/client';
	import type { Dimension, Snapshot } from '$lib/api/types';
	import { formatDateTime, formatDuration } from '$lib/format';

	let {
		open = $bindable(false),
		snapshot,
		onUpdated,
		onDeleted,
	}: {
		open?: boolean;
		snapshot: Snapshot | null;
		onUpdated: (s: Snapshot) => void;
		onDeleted: (id: number) => void;
	} = $props();

	type Form = { x: string; y: string; z: string; biome: string; dimension: string; facing: string };
	let form = $state<Form>({ x: '', y: '', z: '', biome: '', dimension: '', facing: '' });
	let saving = $state(false);
	let deleting = $state(false);

	const str = (v: number | string | null) => (v === null ? '' : String(v));

	$effect(() => {
		if (open && snapshot) {
			form = {
				x: str(snapshot.x),
				y: str(snapshot.y),
				z: str(snapshot.z),
				biome: snapshot.biome ?? '',
				dimension: snapshot.dimension ?? '',
				facing: snapshot.facing ?? '',
			};
		}
	});

	const num = (v: string) => (v.trim() === '' || Number.isNaN(Number(v)) ? null : Number(v));
	const dimensions: { value: Dimension; label: string }[] = [
		{ value: 'overworld', label: 'Overworld' },
		{ value: 'nether', label: 'Nether' },
		{ value: 'end', label: 'End' },
	];

	async function save(event: SubmitEvent) {
		event.preventDefault();
		if (!snapshot) return;
		saving = true;
		try {
			const updated = await api.snapshots.update(snapshot.id, {
				x: num(form.x),
				y: num(form.y),
				z: num(form.z),
				biome: form.biome.trim() || null,
				dimension: (form.dimension || null) as Dimension | null,
				facing: form.facing.trim() || null,
			});
			onUpdated(updated);
			toast.success('Snapshot updated');
			open = false;
		} catch (err) {
			toast.error(err instanceof Error ? err.message : String(err));
		} finally {
			saving = false;
		}
	}

	async function remove() {
		if (!snapshot) return;
		deleting = true;
		try {
			await api.snapshots.remove(snapshot.id);
			onDeleted(snapshot.id);
			open = false;
		} catch (err) {
			toast.error(err instanceof Error ? err.message : String(err));
		} finally {
			deleting = false;
		}
	}
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="sm:max-w-4xl">
		{#if snapshot}
			<Dialog.Header>
				<Dialog.Title class="flex items-center gap-2">
					Snapshot #{snapshot.id}
					<OcrStatusBadge status={snapshot.ocr_status} />
				</Dialog.Title>
				<Dialog.Description class="tabular-nums">
					{formatDateTime(snapshot.captured_at)} · {formatDuration(snapshot.stream_offset_seconds)} into
					session #{snapshot.session_id} · detector confidence {snapshot.confidence.toFixed(2)}
				</Dialog.Description>
			</Dialog.Header>

			<div class="overflow-hidden rounded-lg border bg-black">
				{#if snapshot.image_url}
					<a href={snapshot.image_url} target="_blank" rel="noreferrer">
						<img src={snapshot.image_url} alt="Stored frame" class="aspect-video w-full object-contain" />
					</a>
				{:else}
					<div class="flex aspect-video flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
						<ImageOffIcon class="size-6" />
						No image stored for this snapshot
					</div>
				{/if}
			</div>

			<form id="snapshot-form" onsubmit={save} class="grid grid-cols-2 gap-3 sm:grid-cols-6">
				<div class="grid gap-1.5">
					<Label for="sx">X</Label>
					<Input id="sx" inputmode="decimal" class="font-mono" bind:value={form.x} />
				</div>
				<div class="grid gap-1.5">
					<Label for="sy">Y</Label>
					<Input id="sy" inputmode="decimal" class="font-mono" bind:value={form.y} />
				</div>
				<div class="grid gap-1.5">
					<Label for="sz">Z</Label>
					<Input id="sz" inputmode="decimal" class="font-mono" bind:value={form.z} />
				</div>
				<div class="grid gap-1.5">
					<Label for="sdim">Dimension</Label>
					<Select.Root type="single" bind:value={form.dimension}>
						<Select.Trigger id="sdim" class="w-full">
							{dimensions.find((d) => d.value === form.dimension)?.label ?? 'Unknown'}
						</Select.Trigger>
						<Select.Content>
							{#each dimensions as d (d.value)}
								<Select.Item value={d.value} label={d.label} />
							{/each}
						</Select.Content>
					</Select.Root>
				</div>
				<div class="col-span-2 grid gap-1.5">
					<Label for="sbiome">Biome</Label>
					<Input id="sbiome" placeholder="e.g. minecraft:plains" bind:value={form.biome} />
				</div>
			</form>

			<Dialog.Footer class="sm:justify-between">
				<Button variant="ghost" class="text-muted-foreground" disabled={deleting} onclick={remove}>
					{#if deleting}<Spinner />{:else}<Trash2Icon />{/if}
					Delete snapshot
				</Button>
				<div class="flex gap-2">
					<Button variant="outline" onclick={() => (open = false)}>Close</Button>
					<Button type="submit" form="snapshot-form" disabled={saving}>
						{#if saving}<Spinner />{/if}
						Save values
					</Button>
				</div>
			</Dialog.Footer>
		{/if}
	</Dialog.Content>
</Dialog.Root>
