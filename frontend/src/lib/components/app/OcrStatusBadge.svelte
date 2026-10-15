<script lang="ts">
	import ClockIcon from '@lucide/svelte/icons/clock';
	import CheckIcon from '@lucide/svelte/icons/check';
	import XIcon from '@lucide/svelte/icons/x';
	import PencilIcon from '@lucide/svelte/icons/pencil';
	import { Badge } from '$lib/components/ui/badge';
	import type { OcrStatus } from '$lib/api/types';
	import { cn } from '$lib/utils';

	let { status }: { status: OcrStatus } = $props();

	const config = $derived(
		{
			pending: { label: 'Pending OCR', icon: ClockIcon, class: 'text-muted-foreground' },
			done: { label: 'Read', icon: CheckIcon, class: 'text-emerald-400' },
			failed: { label: 'Failed', icon: XIcon, class: 'text-red-400' },
			manual: { label: 'Manual', icon: PencilIcon, class: 'text-sky-400' },
		}[status],
	);
</script>

<Badge variant="outline" class={cn('gap-1 whitespace-nowrap', config.class)}>
	<config.icon />
	{config.label}
</Badge>
