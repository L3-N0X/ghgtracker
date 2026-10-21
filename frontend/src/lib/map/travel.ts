import type { Dimension, Snapshot } from '$lib/api/types';

/** A snapshot with a known X/Z position, ready to be drawn on the map. */
export interface TravelPoint {
	snapshot: Snapshot;
	x: number;
	z: number;
	/** ms since epoch */
	t: number;
	/** Dimension as read, or carried over from the previous reading when OCR missed it. */
	dimension: Dimension;
}

/**
 * How much time passed between two consecutive points:
 * 0 = continuous travel, 1 = pause, 2 = time jump (or a new session / other dimension in between).
 */
export type GapLevel = 0 | 1 | 2;

export const PAUSE_SECONDS = 90;
export const JUMP_SECONDS = 10 * 60;

export const GAP_LEVELS: { level: GapLevel; label: string; hint: string }[] = [
	{ level: 0, label: 'Continuous', hint: `≤ ${PAUSE_SECONDS} s apart` },
	{ level: 1, label: 'Pause', hint: `${PAUSE_SECONDS / 60}–${JUMP_SECONDS / 60} min apart` },
	{ level: 2, label: 'Time jump', hint: `> ${JUMP_SECONDS / 60} min or new session` },
];

export interface TravelSegment {
	from: TravelPoint;
	to: TravelPoint;
	seconds: number;
	/** horizontal distance in blocks */
	distance: number;
	/** blocks per second (horizontal) */
	speed: number;
	level: GapLevel;
	newSession: boolean;
	/** The player was in another dimension between the two points (e.g. a nether trip). */
	via: Dimension | null;
}

export function toTravelPoints(snapshots: Snapshot[]): TravelPoint[] {
	const sorted = snapshots
		.filter((s) => s.x !== null && s.z !== null)
		.toSorted((a, b) => a.captured_at.localeCompare(b.captured_at) || a.id - b.id);
	let last: Dimension = 'overworld';
	return sorted.map((snapshot) => {
		last = snapshot.dimension ?? last;
		return {
			snapshot,
			x: snapshot.x!,
			z: snapshot.z!,
			t: new Date(snapshot.captured_at).getTime(),
			dimension: last,
		};
	});
}

export function gapLevel(seconds: number, newSession: boolean): GapLevel {
	if (newSession || seconds > JUMP_SECONDS) return 2;
	return seconds > PAUSE_SECONDS ? 1 : 0;
}

/** Connects the points of one dimension in time order. `all` is every point, in time order. */
export function buildSegments(all: TravelPoint[], dimension: Dimension): TravelSegment[] {
	const segments: TravelSegment[] = [];
	let prev: TravelPoint | null = null;
	let via: Dimension | null = null;
	for (const point of all) {
		if (point.dimension !== dimension) {
			if (prev) via = point.dimension;
			continue;
		}
		if (prev) {
			const seconds = Math.max(0, (point.t - prev.t) / 1000);
			const distance = Math.hypot(point.x - prev.x, point.z - prev.z);
			const newSession = point.snapshot.session_id !== prev.snapshot.session_id;
			segments.push({
				from: prev,
				to: point,
				seconds,
				distance,
				speed: seconds > 0 ? distance / seconds : Infinity,
				level: via ? 2 : gapLevel(seconds, newSession),
				newSession,
				via,
			});
		}
		prev = point;
		via = null;
	}
	return segments;
}

/** Rough reading of a speed in blocks per second. */
export function describeSpeed(speed: number): string {
	if (!Number.isFinite(speed)) return 'instant';
	if (speed < 0.3) return 'standing';
	if (speed <= 4.6) return 'walking pace';
	if (speed <= 6) return 'sprinting pace';
	if (speed <= 12) return 'riding / sprint-jumping pace';
	if (speed <= 40) return 'boat / elytra pace';
	return 'teleport or misread?';
}

const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'] as const;

/** Compass direction of a movement. North is -Z, east is +X. */
export function compassDirection(dx: number, dz: number): string {
	const angle = (Math.atan2(dx, -dz) * 180) / Math.PI; // 0 = north, clockwise
	return COMPASS[Math.round(((angle + 360) % 360) / 45) % 8];
}

export interface RecentHeading {
	from: TravelPoint;
	to: TravelPoint;
	dx: number;
	dz: number;
	distance: number;
	seconds: number;
	direction: string;
}

/**
 * Net movement over the last `windowSeconds` of continuous travel that ends at the latest point.
 * Stops at the first time jump, so a new session does not count as "walking there".
 */
export function recentHeading(
	segments: TravelSegment[],
	windowSeconds = 10 * 60,
): RecentHeading | null {
	if (segments.length === 0) return null;
	const to = segments[segments.length - 1].to;
	let from = to;
	for (let i = segments.length - 1; i >= 0; i--) {
		const seg = segments[i];
		if (seg.level === 2 || (to.t - seg.from.t) / 1000 > windowSeconds) break;
		from = seg.from;
	}
	const dx = to.x - from.x;
	const dz = to.z - from.z;
	const distance = Math.hypot(dx, dz);
	if (from === to || distance < 8) return null;
	return {
		from,
		to,
		dx,
		dz,
		distance,
		seconds: (to.t - from.t) / 1000,
		direction: compassDirection(dx, dz),
	};
}

/** "minecraft:dark_forest" -> "Dark Forest" */
export function prettyBiome(biome: string | null): string {
	if (!biome) return 'Unknown biome';
	return biome
		.replace(/^[a-z0-9_.-]+:/, '')
		.split('_')
		.map((w) => w.charAt(0).toUpperCase() + w.slice(1))
		.join(' ');
}

/** Largest "nice" step (1, 2, 5 × 10^k) that is at least `min`. */
export function niceStep(min: number): number {
	const exp = Math.pow(10, Math.floor(Math.log10(min)));
	for (const m of [1, 2, 5, 10]) if (m * exp >= min) return m * exp;
	return 10 * exp;
}

/**
 * Time axis for the timeline strip that keeps time jumps from squashing everything else:
 * a gap longer than `capSeconds` only takes up `capSeconds` worth of width.
 */
export class CompressedTime {
	readonly times: number[];
	readonly positions: number[];
	readonly total: number;
	/** Gaps that were shortened, as [start ms, end ms, position of start, position of end]. */
	readonly breaks: { t0: number; t1: number; u0: number; u1: number }[] = [];

	constructor(times: number[], capSeconds: number) {
		this.times = times;
		this.positions = [];
		let u = 0;
		const cap = capSeconds * 1000;
		times.forEach((t, i) => {
			if (i > 0) {
				const dt = t - times[i - 1];
				const step = Math.min(dt, cap);
				if (dt > cap) this.breaks.push({ t0: times[i - 1], t1: t, u0: u, u1: u + step });
				u += step;
			}
			this.positions.push(u);
		});
		this.total = u;
	}

	/** Time (ms) -> position in 0..1 */
	toUnit(t: number): number {
		const { times, positions } = this;
		if (times.length === 0 || this.total === 0) return 0;
		if (t <= times[0]) return 0;
		if (t >= times[times.length - 1]) return 1;
		let lo = 0;
		let hi = times.length - 1;
		while (hi - lo > 1) {
			const mid = (lo + hi) >> 1;
			if (times[mid] <= t) lo = mid;
			else hi = mid;
		}
		const span = times[hi] - times[lo];
		const f = span === 0 ? 0 : (t - times[lo]) / span;
		return (positions[lo] + f * (positions[hi] - positions[lo])) / this.total;
	}

	/** Position in 0..1 -> time (ms) */
	fromUnit(unit: number): number {
		const { times, positions } = this;
		if (times.length === 0) return 0;
		const u = Math.min(1, Math.max(0, unit)) * this.total;
		let lo = 0;
		let hi = times.length - 1;
		if (hi === 0) return times[0];
		while (hi - lo > 1) {
			const mid = (lo + hi) >> 1;
			if (positions[mid] <= u) lo = mid;
			else hi = mid;
		}
		const span = positions[hi] - positions[lo];
		const f = span === 0 ? 0 : (u - positions[lo]) / span;
		return times[lo] + f * (times[hi] - times[lo]);
	}
}
