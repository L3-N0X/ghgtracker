// Mirrors the backend schemas in backend/src/ghgtracker/models.py and tracker/manager.py

export interface Streamer {
	id: number;
	login: string;
	display_name: string | null;
	notes: string | null;
	created_at: string;
	snapshot_count: number;
	last_snapshot_at: string | null;
}

export interface StreamerCreate {
	login: string;
	display_name?: string | null;
	notes?: string | null;
}

export type TrackerState = 'idle' | 'starting' | 'running' | 'stopping' | 'stopped' | 'error';

export interface TrackerStatus {
	streamer_id: number;
	state: TrackerState;
	session_id: number | null;
	started_at: string | null;
	source: string | null;
	capture_fps: number | null;
	save_interval_seconds: number | null;
	frames_processed: number;
	measured_fps: number;
	f3_frames: number;
	f3_events: number;
	snapshots_saved: number;
	f3_open: boolean;
	last_confidence: number;
	detect_ms: number;
	last_f3_at: string | null;
	last_snapshot_at: string | null;
	error: string | null;
}

export interface TrackerStartRequest {
	source?: string | null;
	capture_fps?: number | null;
	save_interval_seconds?: number | null;
	save_images?: boolean | null;
}

/**
 * pending: waiting for OCR · done: XYZ read and confirmed by the F3 "Block:" line ·
 * unverified: XYZ read but not confirmed · failed: no XYZ readable · manual: entered by hand
 */
export type OcrStatus = 'pending' | 'done' | 'unverified' | 'failed' | 'manual';
export type Dimension = 'overworld' | 'nether' | 'end';

export interface Snapshot {
	id: number;
	session_id: number;
	streamer_id: number;
	f3_event_id: number | null;
	captured_at: string;
	stream_offset_seconds: number;
	confidence: number;
	image_url: string | null;
	ocr_status: OcrStatus;
	raw_text: string | null;
	x: number | null;
	y: number | null;
	z: number | null;
	biome: string | null;
	dimension: Dimension | null;
	facing: string | null;
}

export type SnapshotUpdate = Partial<
	Pick<Snapshot, 'x' | 'y' | 'z' | 'biome' | 'dimension' | 'facing'>
>;

export interface F3Event {
	id: number;
	session_id: number;
	streamer_id: number;
	opened_at: string;
	closed_at: string | null;
	frame_count: number;
	peak_confidence: number;
	duration_seconds: number | null;
}

export interface TrackingSession {
	id: number;
	streamer_id: number;
	started_at: string;
	ended_at: string | null;
	status: 'running' | 'stopped' | 'error';
	source: string;
	capture_fps: number;
	save_interval_seconds: number;
	frames_processed: number;
	f3_frames: number;
	f3_events: number;
	snapshots_saved: number;
	error: string | null;
}

export interface Page<T> {
	items: T[];
	total: number;
	limit: number;
	offset: number;
}

interface ColumnAnalysis {
	line_count: number;
	starts_at_top: boolean;
	/** line pitch in source pixels (9 GUI px) */
	pitch: number | null;
	/** distance of the text from the screen edge in source pixels */
	anchor: number | null;
	/** how well glyph edges sit on the GUI pixel grid, 0..1 */
	grid: number;
}

/** OCR result of the detector lab (backend vision/extractor.py ExtractionResult) */
export interface OcrReading {
	x: number | null;
	y: number | null;
	z: number | null;
	/** XYZ matches the "Block:" line of the F3 screen */
	confirmed: boolean;
	biome: string | null;
	dimension: Dimension | null;
	facing: string | null;
	raw_text: string | null;
	engine: string | null;
	elapsed_ms: number;
}

export interface OcrInfo {
	engine: string;
	state: 'off' | 'loading' | 'ready' | 'error';
	queued: number;
	processed: number;
	skipped: number;
	last_ms: number | null;
	error: string | null;
}

export interface DetectionResult {
	detected: boolean;
	confidence: number;
	left: ColumnAnalysis;
	right: ColumnAnalysis;
	gui_scale: number | null;
	work_scale: number;
	elapsed_ms: number;
	width: number;
	height: number;
	/** null if no F3 screen was detected or OCR is switched off */
	ocr: OcrReading | null;
	overlay_jpeg: string;
}

export type ServerEvent =
	| { type: 'tracker.status'; status: TrackerStatus }
	| { type: 'f3.opened'; streamer_id: number; event_id: number; at: string }
	| { type: 'f3.closed'; streamer_id: number; event_id: number; frame_count: number; at: string }
	| { type: 'snapshot.created'; streamer_id: number; snapshot: Snapshot }
	| { type: 'snapshot.updated'; streamer_id: number; snapshot: Snapshot };
