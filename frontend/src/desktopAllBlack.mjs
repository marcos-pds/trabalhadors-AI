// The Electron dock is intentionally narrower than 1024 px, even on a
// desktop display. Use the *screen* width, not window.innerWidth, for the
// desktop-only theme gate. The browser and PWA never have the Electron bridge.
export const MIN_ALL_BLACK_SCREEN_WIDTH = 1024

export function shouldUseDesktopAllBlack(desktopMode, screenWidth) {
  return desktopMode === true &&
    Number.isFinite(screenWidth) &&
    screenWidth >= MIN_ALL_BLACK_SCREEN_WIDTH
}

export function getDesktopAllBlackState(windowLike, desktopMode) {
  return shouldUseDesktopAllBlack(desktopMode, Number(windowLike?.screen?.width))
}

export function applyDesktopAllBlack(root, enabled) {
  root?.classList?.toggle('central-desktop-all-black', enabled === true)
  return enabled === true
}
