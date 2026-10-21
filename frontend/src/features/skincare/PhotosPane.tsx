import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, failText, ok, RequestError } from '@/api/client'
import { DateField } from '@/components/controls/DateField'
import { PhotoRibbon } from '@/components/controls/PhotoRibbon'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import type { SkincareView } from './types'

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

  const upload = useMutation({
    mutationFn: async () => {
      if (files === null || files.length === 0) return
      const fd = new FormData()
      for (const file of Array.from(files)) fd.append('files', file)
      fd.append('date', date)
      if (note.trim()) fd.append('note', note.trim())
      const res = await fetch('/api/v1/skincare/photos', { method: 'POST', body: fd, credentials: 'same-origin' })
      if (!res.ok) throw new RequestError(res.status)
    },
    onSuccess: () => {
      refresh()
      toast(t('app.saved'))
      setFiles(null)
      setNote('')
      setInputKey((k) => k + 1)
    },
    onError: () => toast(t('app.upload_failed'), { icon: 'warn' }),
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
          onSubmit={(e) => {
            e.preventDefault()
            upload.mutate()
          }}
        >
          <label className="field">
            <span className="flabel">{t('common.date')}</span>
            <DateField value={date} onChange={setDate} max={view.today} />
          </label>
          <label className="field">
            <span className="flabel">{t('common.note_optional')}</span>
            <input type="text" className="input" value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <div className="field">
            <span className="flabel">{t('app.skincare.photo_files')}</span>
            <span>
              <label className="ghost sk-file">
                <Icon name="image" />
                {t('app.skincare.photo_pick')}
                <input key={inputKey} type="file" accept="image/*" multiple onChange={(e) => setFiles(e.target.files)} />
              </label>
              {files !== null && files.length > 0 && (
                <span className="sk-file-n num"> {t('app.skincare.photo_picked', { n: files.length })}</span>
              )}
            </span>
          </div>
          <div className="form-acts">
            <button type="submit" className="btn grow" disabled={upload.isPending || files === null || files.length === 0}>
              {t('app.skincare.photo_upload')}
            </button>
          </div>
        </form>
      </Section>
    </>
  )
}
