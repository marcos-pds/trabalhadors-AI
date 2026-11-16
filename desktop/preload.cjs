const { contextBridge, ipcRenderer } = require('electron')

// Establish a transparent surface before React mounts. Only the installed
// Electron window runs this preload; a normal browser page remains unchanged.
function prepareTransparentDesktop() {
  const root = document.documentElement
  if (root) {
    root.classList.add('central-desktop-shell')
    root.classList.remove('light')
    root.style.setProperty('background', 'transparent', 'important')
  }
  if (document.body) {
    document.body.style.setProperty('background', 'transparent', 'important')
  }
}
prepareTransparentDesktop()
document.addEventListener('DOMContentLoaded', prepareTransparentDesktop, { once: true })

// No arbitrary IPC, Node, filesystem or tokens are exposed to web content.
contextBridge.exposeInMainWorld('centralDesktop', Object.freeze({
  isDesktop: true,
  setExpanded(open) {
    ipcRenderer.send('central-desktop:set-expanded', open === true)
  },
}))
