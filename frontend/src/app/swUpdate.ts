interface WorkerContainer {
  controller: object | null
  addEventListener: (type: 'controllerchange', listener: () => void) => void
}

/** A new build's worker takes the page over as soon as it is installed, and the page then still
 *  runs the old code against files the new worker has dropped. One reload puts them back in step.
 *  The first visit has no worker yet, and gaining one there changes nothing on screen. */
export function reloadOnNewWorker(container: WorkerContainer, reload: () => void): void {
  if (container.controller === null) return
  let reloaded = false
  container.addEventListener('controllerchange', () => {
    if (reloaded) return
    reloaded = true
    reload()
  })
}
