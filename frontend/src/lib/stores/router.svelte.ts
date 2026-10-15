/** Minimal hash router: `#/` (home), `#/streamers/:id` and `#/lab`. */

export type Route = { name: 'home' } | { name: 'streamer'; id: number } | { name: 'lab' };

function parse(hash: string): Route {
	const path = hash.replace(/^#/, '') || '/';
	const streamer = path.match(/^\/streamers\/(\d+)\/?$/);
	if (streamer) return { name: 'streamer', id: Number(streamer[1]) };
	if (path === '/lab') return { name: 'lab' };
	return { name: 'home' };
}

class Router {
	route = $state<Route>(parse(location.hash));

	constructor() {
		window.addEventListener('hashchange', () => {
			this.route = parse(location.hash);
		});
	}

	go(path: string) {
		location.hash = path;
	}
}

export const router = new Router();
