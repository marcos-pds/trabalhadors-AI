const { contextBridge, ipcRenderer } = require('electron')

// No arbitrary IPC, Node, filesystem or tokens are exposed to web content.
contextBridge.exposeInMainWorld('centralDesktop', Object.freeze({
  isDesktop: true,
  setExpanded(open) {
    ipcRenderer.send('central-desktop:set-expanded', open === true)
  },
}))
