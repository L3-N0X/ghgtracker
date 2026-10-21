import type {
	DetectionResult,
	F3Event,
	OcrInfo,
	Page,
	Snapshot,
	SnapshotUpdate,
	Streamer,
	StreamerCreate,
	TrackerStartRequest,
	TrackerStatus,
	TrackingSession,
} from './types';

export class ApiError extends Error {
	constructor(
		public status: number,
		message: string,
	) {
		super(message);
	}
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
	const headers = new Headers(init.headers);
	if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
	const res = await fetch(`/api${path}`, { ...init, headers });
	if (!res.ok) {
		let message = res.statusText;
		try {
			const body = await res.json();
			message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
		} catch {
			// keep statusText
		}
		throw new ApiError(res.status, message);
	}
	return (res.status === 204 ? undefined : await res.json()) as T;
}

function query(params: Record<string, string | number | boolean | undefined | null>): string {
	const search = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
	}
	const qs = search.toString();
	return qs ? `?${qs}` : '';
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
	streamers: {
		list: () => request<Streamer[]>('/streamers'),
		get: (id: number) => request<Streamer>(`/streamers/${id}`),
		create: (body: StreamerCreate) =>
			request<Streamer>('/streamers', { method: 'POST', body: json(body) }),
		update: (id: number, body: Partial<StreamerCreate>) =>
			request<Streamer>(`/streamers/${id}`, { method: 'PATCH', body: json(body) }),
		remove: (id: number) => request<void>(`/streamers/${id}`, { method: 'DELETE' }),
		live: (id: number) => request<{ login: string; live: boolean }>(`/streamers/${id}/live`),
		sessions: (id: number) => request<TrackingSession[]>(`/streamers/${id}/sessions`),
	},
	tracker: {
		all: () => request<TrackerStatus[]>('/trackers'),
		status: (streamerId: number) => request<TrackerStatus>(`/streamers/${streamerId}/tracker`),
		start: (streamerId: number, body: TrackerStartRequest) =>
			request<TrackerStatus>(`/streamers/${streamerId}/tracker/start`, {
				method: 'POST',
				body: json(body),
			}),
		stop: (streamerId: number) =>
			request<TrackerStatus>(`/streamers/${streamerId}/tracker/stop`, { method: 'POST' }),
		frameUrl: (streamerId: number, overlay: boolean, cacheBust: number) =>
			`/api/streamers/${streamerId}/tracker/frame.jpg${query({ overlay: String(overlay), t: cacheBust })}`,
	},
	snapshots: {
		list: (params: {
			streamer_id?: number;
			session_id?: number;
			limit?: number;
			offset?: number;
			order?: 'asc' | 'desc';
			/** ISO timestamp */
			since?: string;
			/** only snapshots with known X and Z */
			has_position?: boolean;
		}) => request<Page<Snapshot>>(`/snapshots${query(params)}`),
		update: (id: number, body: SnapshotUpdate) =>
			request<Snapshot>(`/snapshots/${id}`, { method: 'PATCH', body: json(body) }),
		remove: (id: number) => request<void>(`/snapshots/${id}`, { method: 'DELETE' }),
		/** Read one stored snapshot again right now. */
		ocr: (id: number) => request<Snapshot>(`/snapshots/${id}/ocr`, { method: 'POST' }),
		/** Queue unread (pending / failed) stored snapshots for OCR in the background. */
		queueOcr: (params: { streamer_id?: number; session_id?: number }) =>
			request<{ queued: number }>(`/snapshots/ocr${query(params)}`, { method: 'POST' }),
	},
	ocr: {
		info: () => request<OcrInfo>('/ocr'),
	},
	f3Events: {
		list: (params: { streamer_id?: number; session_id?: number; limit?: number; offset?: number }) =>
			request<Page<F3Event>>(`/f3-events${query(params)}`),
	},
	detect: (file: File) => {
		const body = new FormData();
		body.append('file', file);
		return request<DetectionResult>('/detect', { method: 'POST', body });
	},
};
