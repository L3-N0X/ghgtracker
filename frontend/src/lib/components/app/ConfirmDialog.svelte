<script lang="ts">
	import * as Dialog from '$lib/components/ui/dialog';
	import { Button } from '$lib/components/ui/button';
	import { Spinner } from '$lib/components/ui/spinner';

	let {
		open = $bindable(false),
		title,
		description,
		confirmLabel = 'Confirm',
		destructive = false,
		onConfirm,
	}: {
		open?: boolean;
		title: string;
		description: string;
		confirmLabel?: string;
		destructive?: boolean;
		onConfirm: () => Promise<void> | void;
	} = $props();

	let busy = $state(false);

	async function confirm() {
		busy = true;
		try {
			await onConfirm();
			open = false;
		} finally {
			busy = false;
		}
	}
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="sm:max-w-md">
		<Dialog.Header>
			<Dialog.Title>{title}</Dialog.Title>
			<Dialog.Description>{description}</Dialog.Description>
		</Dialog.Header>
		<Dialog.Footer>
			<Button variant="outline" onclick={() => (open = false)}>Cancel</Button>
			<Button variant={destructive ? 'destructive' : 'default'} disabled={busy} onclick={confirm}>
				{#if busy}<Spinner />{/if}
				{confirmLabel}
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
