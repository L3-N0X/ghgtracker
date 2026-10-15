<script lang="ts">
	import { toast } from 'svelte-sonner';
	import * as Dialog from '$lib/components/ui/dialog';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import { Label } from '$lib/components/ui/label';
	import { Spinner } from '$lib/components/ui/spinner';
	import { streamers } from '$lib/stores/streamers.svelte';
	import { router } from '$lib/stores/router.svelte';

	let { open = $bindable(false) }: { open?: boolean } = $props();

	let login = $state('');
	let displayName = $state('');
	let submitting = $state(false);
	let error = $state<string | null>(null);

	$effect(() => {
		if (open) {
			login = '';
			displayName = '';
			error = null;
		}
	});

	async function submit(event: SubmitEvent) {
		event.preventDefault();
		submitting = true;
		error = null;
		try {
			const streamer = await streamers.add({
				login,
				display_name: displayName.trim() || null,
			});
			toast.success(`Added ${streamer.display_name || streamer.login}`);
			open = false;
			router.go(`/streamers/${streamer.id}`);
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
		} finally {
			submitting = false;
		}
	}
</script>

<Dialog.Root bind:open>
	<Dialog.Content class="sm:max-w-md">
		<form onsubmit={submit} class="grid gap-4">
			<Dialog.Header>
				<Dialog.Title>Add streamer</Dialog.Title>
				<Dialog.Description>
					Enter a Twitch login or paste the channel URL. The tracker reads this channel's live
					stream.
				</Dialog.Description>
			</Dialog.Header>

			<div class="grid gap-2">
				<Label for="login">Twitch channel</Label>
				<Input
					id="login"
					placeholder="e.g. papaplatte or https://twitch.tv/papaplatte"
					bind:value={login}
					autocomplete="off"
					required
					aria-invalid={error ? true : undefined}
				/>
			</div>
			<div class="grid gap-2">
				<Label for="display-name">Display name <span class="text-muted-foreground">(optional)</span></Label>
				<Input id="display-name" placeholder="Shown in the sidebar" bind:value={displayName} />
			</div>
			{#if error}
				<p class="text-sm text-destructive">{error}</p>
			{/if}

			<Dialog.Footer>
				<Button variant="outline" type="button" onclick={() => (open = false)}>Cancel</Button>
				<Button type="submit" disabled={submitting || !login.trim()}>
					{#if submitting}<Spinner />{/if}
					Add streamer
				</Button>
			</Dialog.Footer>
		</form>
	</Dialog.Content>
</Dialog.Root>
