// A desktop mode is only opted into by the Electron preload bridge.
// Browser tabs and installed browser PWAs keep the existing web interface.
export function isCentralDesktop(windowLike) {
  const bridge = windowLike?.centralDesktop
  return bridge?.isDesktop === true && typeof bridge?.setExpanded === 'function'
}
