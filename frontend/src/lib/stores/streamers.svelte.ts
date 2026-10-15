import { api } from '$lib/api/client';
import type { Streamer, StreamerCreate } from '$lib/api/types';
import { live } from './live.svelte';

class StreamersStore {
	items = $state<Streamer[]>([]);
	loading = $state(true);
	error = $state<string | null>(null);

	constructor() {
		// Keep the sidebar counters fresh without refetching.
		live.subscribe((event) => {
			if (event.type !== 'snapshot.created') return;
			const streamer = this.items.find((s) => s.id === event.streamer_id);
			if (streamer) {
				streamer.snapshot_count += 1;
				streamer.last_snapshot_at = event.snapshot.captured_at;
			}
		});
	}

	byId(id: number): Streamer | undefined {
		return this.items.find((s) => s.id === id);
	}

	async load() {
		this.loading = true;
		try {
			this.items = await api.streamers.list();
			this.error = null;
		} catch (err) {
			this.error = err instanceof Error ? err.message : String(err);
		} finally {
			this.loading = false;
		}
	}

	async add(body: StreamerCreate): Promise<Streamer> {
		const streamer = await api.streamers.create(body);
		this.items = [...this.items, streamer].sort((a, b) => a.login.localeCompare(b.login));
		return streamer;
	}

	async update(id: number, body: Partial<StreamerCreate>) {
		const updated = await api.streamers.update(id, body);
		this.items = this.items.map((s) => (s.id === id ? updated : s));
	}

	async remove(id: number) {
		await api.streamers.remove(id);
		this.items = this.items.filter((s) => s.id !== id);
	}
}

export const streamers = new StreamersStore();

export function streamerName(s: Pick<Streamer, 'login' | 'display_name'>): string {
	return s.display_name || s.login;
}
