/* 타임라인 아이콘 (16px 기준 SVG, 색은 currentColor). */

const svg = body => `<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor"
  stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;

export const ICONS = {
  start: svg('<path d="M4 3v10M13 3 7 8l6 5z" fill="currentColor"/>'),
  end: svg('<path d="M12 3v10M3 3l6 5-6 5z" fill="currentColor"/>'),
  prevFrame: svg('<path d="M10 3 5 8l5 5"/>'),
  nextFrame: svg('<path d="m6 3 5 5-5 5"/>'),
  play: svg('<path d="M5 3l8 5-8 5z" fill="currentColor"/>'),
  pause: svg('<path d="M5 3v10M11 3v10" stroke-width="2.4"/>'),
  magnet: svg('<path d="M4 2v6a4 4 0 0 0 8 0V2M4 5h3M9 5h3"/>'),
  zoomIn: svg('<circle cx="7" cy="7" r="4.5"/><path d="m10.5 10.5 3 3M5 7h4M7 5v4"/>'),
  zoomOut: svg('<circle cx="7" cy="7" r="4.5"/><path d="m10.5 10.5 3 3M5 7h4"/>'),
  fit: svg('<path d="M2 6V2h4M14 6V2h-4M2 10v4h4M14 10v4h-4"/>'),
  scissors: svg('<circle cx="4.5" cy="11.5" r="2"/><circle cx="11.5" cy="11.5" r="2"/><path d="M6 10 12 2M10 10 4 2"/>'),
  help: svg('<circle cx="8" cy="8" r="6.2"/><path d="M6.3 6.2a1.8 1.8 0 1 1 2.6 1.6c-.6.3-.9.7-.9 1.3M8 11.4v.1"/>'),
  eye: svg('<path d="M1.5 8S4 3.5 8 3.5 14.5 8 14.5 8 12 12.5 8 12.5 1.5 8 1.5 8z"/><circle cx="8" cy="8" r="2"/>'),
  eyeOff: svg('<path d="M2 2l12 12M6.5 6.6a2 2 0 0 0 2.9 2.9M4.2 4.4C2.5 5.6 1.5 8 1.5 8S4 12.5 8 12.5c1.4 0 2.6-.5 3.6-1.2M7 3.6c.3 0 .7-.1 1-.1 4 0 6.5 4.5 6.5 4.5a12 12 0 0 1-1.6 2.2"/>'),
  lock: svg('<rect x="3" y="7" width="10" height="7" rx="1.5"/><path d="M5 7V5a3 3 0 0 1 6 0v2"/>'),
  unlock: svg('<rect x="3" y="7" width="10" height="7" rx="1.5"/><path d="M5 7V5a3 3 0 0 1 5.8-1"/>'),
  height: svg('<path d="M8 2v12M5 5l3-3 3 3M5 11l3 3 3-3"/>'),
  captions: svg('<rect x="1.5" y="3" width="13" height="10" rx="2"/><path d="M4.5 7h3M9 7h2.5M4.5 10h5M11 10h.5"/>'),
  text: svg('<path d="M3 4V3h10v1M8 3v10M6 13h4"/>'),
  video: svg('<rect x="1.5" y="3.5" width="9" height="9" rx="1.5"/><path d="m10.5 7 4-2.5v7l-4-2.5"/>'),
  audio: svg('<path d="M2 6v4M5 4v8M8 2v12M11 5v6M14 7v2"/>'),
};
