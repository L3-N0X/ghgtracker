/** A shared 1 Hz clock for "time ago" / uptime displays. */
class Clock {
	current = $state(Date.now());

	constructor() {
		setInterval(() => {
			this.current = Date.now();
		}, 1000);
	}
}

export const now = new Clock();
