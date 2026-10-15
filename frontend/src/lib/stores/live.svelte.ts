import { api } from '$lib/api/client';
import type { ServerEvent, TrackerStatus } from '$lib/api/types';

type Listener = (event: ServerEvent) => void;

/**
 * Live connection to the backend event socket. Keeps the latest tracker status per streamer
 * and lets components subscribe to raw events (e.g. new snapshots for the coordinate log).
 */
class LiveStore {
	connected = $state(false);
	trackers = $state<Record<number, TrackerStatus>>({});

	#socket: WebSocket | null = null;
	#listeners = new Set<Listener>();
	#retryMs = 1000;
	#started = false;

	start() {
		if (this.#started) return;
		this.#started = true;
		this.#connect();
	}

	subscribe(listener: Listener): () => void {
		this.#listeners.add(listener);
		return () => this.#listeners.delete(listener);
	}

	tracker(streamerId: number): TrackerStatus | undefined {
		return this.trackers[streamerId];
	}

	setStatus(status: TrackerStatus) {
		this.trackers[status.streamer_id] = status;
	}

	async refresh() {
		const statuses = await api.tracker.all();
		for (const status of statuses) this.setStatus(status);
	}

	#connect() {
		const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
		const socket = new WebSocket(`${protocol}://${location.host}/api/ws`);
		this.#socket = socket;

		socket.onopen = () => {
			this.connected = true;
			this.#retryMs = 1000;
			// Catch up on anything missed while disconnected.
			this.refresh().catch(() => {});
		};
		socket.onmessage = (message) => {
			const event = JSON.parse(message.data) as ServerEvent;
			if (event.type === 'tracker.status') this.setStatus(event.status);
			for (const listener of this.#listeners) listener(event);
		};
		socket.onclose = () => {
			this.connected = false;
			this.#socket = null;
			setTimeout(() => this.#connect(), this.#retryMs);
			this.#retryMs = Math.min(this.#retryMs * 2, 15000);
		};
		socket.onerror = () => socket.close();
	}
}

export const live = new LiveStore();
