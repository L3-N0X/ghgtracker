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
