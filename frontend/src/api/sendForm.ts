import { RequestError } from './client'

/** A multipart POST that reports how much of the body has gone out, from 0 to 1. `fetch` cannot:
 *  a phone sending a few full-size photos over mobile data would sit silent for a minute.
 *  A refusal throws a `RequestError` with its status; a dropped connection, with status 0. */
export function sendForm(url: string, body: FormData, onProgress: (sent: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0) onProgress(Math.min(1, e.loaded / e.total))
    }
    xhr.onload = () => (xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new RequestError(xhr.status)))
    xhr.onerror = () => reject(new RequestError(0))
    xhr.onabort = () => reject(new RequestError(0))
    xhr.send(body)
  })
}
