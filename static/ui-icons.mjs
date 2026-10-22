/* Self-contained outline icons; no network, package manager or runtime framework. */
const paths=Object.freeze({
 menu:'<path d="M4 7h16M4 12h16M4 17h16"/>',
 close:'<path d="M18 6 6 18M6 6l12 12"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',
 paperclip:'<path d="m20.5 11.5-8.9 8.9a6 6 0 0 1-8.5-8.5l9.4-9.4a4 4 0 0 1 5.7 5.7l-9.4 9.4a2 2 0 0 1-2.8-2.8l8.8-8.8"/>',
 send:'<path d="M12 19V5M5 12l7-7 7 7"/>',
 sparkles:'<path d="m12 2 2.4 7.6L22 12l-7.6 2.4L12 22l-2.4-7.6L2 12l7.6-2.4L12 2Z"/>',
 dashboard:'<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
 chat:'<path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H6l-3 2v-5.5a7.5 7.5 0 1 1 17-4Z"/>',
 agents:'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
 workflows:'<rect x="2" y="4" width="7" height="6" rx="1"/><rect x="15" y="14" width="7" height="6" rx="1"/><path d="M9 7h4a4 4 0 0 1 4 4v3M14 11l3 3 3-3"/>',
 projects:'<path d="M3 7V5a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/>',
 workspace:'<path d="M7 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-2M10 3h7l4 4v6h-11V3ZM16 3v5h5"/>',
 skills:'<path d="m12 2 2.4 7.6L22 12l-7.6 2.4L12 22l-2.4-7.6L2 12l7.6-2.4L12 2Z"/>',
 history:'<path d="M3 12a9 9 0 1 0 2.7-6.4L3 8M3 3v5h5"/><path d="M12 7v5l4 2"/>',
 monitoring:'<path d="M3 12h4l3-8 4 16 3-8h4"/>',
 providers:'<path d="M8 3v5M16 3v5M5 8h14v4a7 7 0 0 1-14 0V8ZM12 19v3"/>',
 settings:'<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.5-2.5 1a7 7 0 0 0-1.8-1L14 3h-4l-.6 3a7 7 0 0 0-1.8 1L5 6l-2 3.5L5 11a7 7 0 0 0 0 2l-2 1.5L5 18l2.6-1a7 7 0 0 0 1.8 1L10 21h4l.6-3a7 7 0 0 0 1.8-1L19 18l2-3.5-2-1.5a7 7 0 0 0 .1-1Z"/>',
 code:'<path d="m8 8-4 4 4 4m8-8 4 4-4 4"/>',
 search:'<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
 check:'<path d="m5 12 4 4L19 6"/>',
 stop:'<rect x="6" y="6" width="12" height="12" rx="2"/>'
});
/** Inline SVG from fixed internal paths, never from user-provided text. */
export function uiSvg(name,size=20){
 const glyph=paths[name]||paths.sparkles;
 const dimension=Math.max(12,Math.min(36,Number(size)||20));
 return `<svg class="ui-icon" width="${dimension}" height="${dimension}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${glyph}</svg>`;
}
