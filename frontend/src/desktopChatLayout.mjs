// Electron-only three-state chat transition rules. Kept pure so a click on
// the avatar can never accidentally expand the conversation panel.
export function desktopChatLayout({ authenticated, expanded, composerOpen, page }) {
  if (!authenticated || expanded) return 'full'
  return composerOpen && page === 'chat' ? 'compose' : 'dock'
}

export function nextAvatarChat({ page, expanded, composerOpen }) {
  if (page === 'chat' && (expanded || composerOpen)) {
    return { page: 'chat', expanded: false, composerOpen: false }
  }
  return { page: 'chat', expanded: false, composerOpen: true }
}

export function afterSuccessfulSend({ desktopMode, expanded, composerOpen }) {
  return desktopMode ? { expanded: true, composerOpen: false } : { expanded, composerOpen }
}
