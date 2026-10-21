const timeFmt = new Intl.DateTimeFormat(undefined, {
	hour: '2-digit',
	minute: '2-digit',
	second: '2-digit',
});
const dateTimeFmt = new Intl.DateTimeFormat(undefined, {
	month: 'short',
	day: '2-digit',
	hour: '2-digit',
	minute: '2-digit',
	second: '2-digit',
});

export function formatTime(iso: string | null | undefined): string {
	return iso ? timeFmt.format(new Date(iso)) : '—';
}

export function formatDateTime(iso: string | null | undefined): string {
	return iso ? dateTimeFmt.format(new Date(iso)) : '—';
}

export function formatDuration(totalSeconds: number | null | undefined): string {
	if (totalSeconds === null || totalSeconds === undefined) return '—';
	if (totalSeconds < 10) return `${totalSeconds.toFixed(2)} s`;
	const s = Math.floor(totalSeconds);
	const h = Math.floor(s / 3600);
	const m = Math.floor((s % 3600) / 60);
	const sec = s % 60;
	const pad = (n: number) => String(n).padStart(2, '0');
	return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

export function formatRelative(iso: string | null | undefined, now = Date.now()): string {
	if (!iso) return 'never';
	const diff = Math.max(0, (now - new Date(iso).getTime()) / 1000);
	if (diff < 5) return 'just now';
	if (diff < 60) return `${Math.floor(diff)} s ago`;
	if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
	if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
	return `${Math.floor(diff / 86400)} d ago`;
}

export function formatCoord(value: number | null | undefined, digits = 1): string {
	return value === null || value === undefined ? '—' : value.toFixed(digits);
}

export function formatNumber(value: number): string {
	return value.toLocaleString();
}

/** A span of time for humans: "45 s", "3 min 12 s", "2 h 05 min", "3 d 4 h". */
export function formatSpan(totalSeconds: number): string {
	const s = Math.round(totalSeconds);
	if (s < 60) return `${s} s`;
	const pad = (n: number) => String(n).padStart(2, '0');
	if (s < 3600) {
		const sec = s % 60;
		return sec ? `${Math.floor(s / 60)} min ${pad(sec)} s` : `${s / 60} min`;
	}
	if (s < 86400) return `${Math.floor(s / 3600)} h ${pad(Math.floor((s % 3600) / 60))} min`;
	return `${Math.floor(s / 86400)} d ${Math.floor((s % 86400) / 3600)} h`;
}

export function formatBlocks(blocks: number): string {
	return blocks >= 10000 ? `${(blocks / 1000).toFixed(1)}k blocks` : `${Math.round(blocks).toLocaleString()} blocks`;
}
