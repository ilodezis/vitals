import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, failText, ok, RequestError } from '@/api/client'
import { sendForm } from '@/api/sendForm'
import { DateField } from '@/components/controls/DateField'
import { PhotoRibbon } from '@/components/controls/PhotoRibbon'
import { Section } from '@/components/controls/Section'
import { dismissToast, toast, updateToast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import type { SkincareView } from './types'

/** How many photos the server takes in one upload. */
export const MAX_PHOTOS = 5

/** What the upload says while it runs: the share of bytes sent, then the wait for the server. */
export function uploadStatus(sent: number): { pct: number; saving: boolean } {
  return { pct: Math.round(sent * 100), saving: sent >= 1 }
}

/** The face photo diary: the same tiles as the weight's progress photos, uploaded the same way. */
export function PhotosPane({ view }: { view: SkincareView }) {
  const { t } = useT()
  const queryClient = useQueryClient()
  const [date, setDate] = useState(view.today)
  const [note, setNote] = useState('')
  const [files, setFiles] = useState<FileList | null>(null)
  // A new key empties the file input after an upload; React cannot set its value.
  const [inputKey, setInputKey] = useState(0)

  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['skincare'] })

  // Share of the body sent, 0–1, while an upload runs; null when idle.
  const [sent, setSent] = useState<number | null>(null)
  const count = files?.length ?? 0
  const tooMany = count > MAX_PHOTOS

  const statusText = (share: number) => {
    const s = uploadStatus(share)
    return s.saving ? t('app.skincare.photo_saving') : t('app.skincare.photo_uploading', { n: count, pct: s.pct })
  }

  const upload = useMutation({
    mutationFn: async () => {
      if (files === null) return
      const fd = new FormData()
      for (const file of Array.from(files)) fd.append('files', file)
      fd.append('date', date)
      if (note.trim()) fd.append('note', note.trim())
      setSent(0)
      // The status stays up for the whole upload, and follows it to another screen.
      const id = toast(statusText(0), { icon: 'upload', persist: true, progress: 0 })
      try {
        await sendForm('/api/v1/skincare/photos', fd, (share) => {
          setSent(share)
          updateToast(id, { text: statusText(share), progress: share })
        })
      } finally {
        dismissToast(id)
        setSent(null)
      }
    },
    onSuccess: () => {
      refresh()
      toast(t('app.skincare.photo_saved', { n: count }))
      setFiles(null)
      setNote('')
      setInputKey((k) => k + 1)
    },
    onError: (err) =>
      toast(err instanceof RequestError && err.status === 413 ? t('app.skincare.photo_too_big') : t('app.upload_failed'), { icon: 'warn' }),
  })

  const remove = useMutation({
    mutationFn: (id: number) => ok(api.DELETE('/api/v1/skincare/photos/{photo_id}', { params: { path: { photo_id: id } } })),
    onSuccess: () => {
      refresh()
      toast(t('common.deleted'))
    },
    onError: (err) => toast(failText(err, t('app.delete_failed')), { icon: 'warn' }),
  })

  return (
    <>
      <Section title={t('app.skincare.photos_title')} meta={t('app.skincare.photos_sub')}>
        <PhotoRibbon
          photos={view.photos}
          onDelete={(id) => remove.mutate(id)}
          label={t('app.skincare.photo_label')}
          openLabel={t('app.skincare.photo_open')}
        />
      </Section>
      <Section>
        <form
          className="panel form sk-form"
          aria-busy={upload.isPending}
          onSubmit={(e) => {
            e.preventDefault()
            if (count > 0 && !tooMany && !upload.isPending) upload.mutate()
          }}
        >
          <label className="field">
            <span className="flabel">{t('common.date')}</span>
            <DateField value={date} onChange={setDate} max={view.today} />
          </label>
          <label className="field">
            <span className="flabel">{t('common.note_optional')}</span>
            <input type="text" className="input" value={note} disabled={upload.isPending} onChange={(e) => setNote(e.target.value)} />
          </label>
          <div className="field">
            <span className="flabel">{t('app.skincare.photo_files')}</span>
            <span>
              <label className="ghost sk-file">
                <Icon name="image" />
                {t('app.skincare.photo_pick')}
                <input
                  key={inputKey}
                  type="file"
                  accept="image/*"
                  multiple
                  disabled={upload.isPending}
                  onChange={(e) => setFiles(e.target.files)}
                />
              </label>
              {count > 0 && (
                <span className={cx('sk-file-n num', tooMany && 'sk-file-over')}>
                  {' '}
                  {tooMany ? t('app.skincare.photo_too_many', { n: count, max: MAX_PHOTOS }) : t('app.skincare.photo_picked', { n: count })}
                </span>
              )}
            </span>
          </div>
          <div className="form-acts">
            <button type="submit" className="btn grow" disabled={upload.isPending || count === 0 || tooMany}>
              {sent === null ? t('app.skincare.photo_upload') : statusText(sent)}
            </button>
          </div>
        </form>
      </Section>
    </>
  )
}
