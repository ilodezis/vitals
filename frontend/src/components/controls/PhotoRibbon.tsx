import { useState } from 'react'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { longDate, parseIsoDate, shortDate } from '@/lib/dates'
import { ConfirmButton } from './ConfirmButton'

export interface RibbonPhoto {
  id: number
  date: string
  /** The original, as uploaded: only behind the "Original" link, never drawn here. */
  url: string
  /** The small copy the tile shows, and the screen-sized one the opened photo shows. */
  thumbUrl: string
  screenUrl: string
  note?: string | null
}

interface PhotoRibbonProps {
  photos: readonly RibbonPhoto[]
  onDelete: (id: number) => void
  /** What the photos are ("Photo", "Face photo"): the image's alt and the dialog's name. */
  label: string
  /** The tile's accessible name. */
  openLabel: string
}

/** A dated photo diary: a row of tiles, newest first, and one photo shown large with its
 *  delete. The same control for the weight's progress photos and the face photos. */
export function PhotoRibbon({ photos, onDelete, label, openLabel }: PhotoRibbonProps) {
  const { t, lang } = useT()
  const [largeId, setLargeId] = useState<number | null>(null)
  const large = largeId === null ? undefined : photos.find((p) => p.id === largeId)

  return (
    <>
      <div className="ribbon">
        {photos.length === 0 ? (
          <span className="m ribbon-empty">{t('app.empty')}</span>
        ) : (
          photos.map((ph) => (
            <button key={ph.id} type="button" className="ph-tile" aria-label={openLabel} onClick={() => setLargeId(ph.id)}>
              <span className="im">
                <img src={ph.thumbUrl} alt={ph.note ?? label} loading="lazy" decoding="async" />
              </span>
              <span className="m num">{shortDate(parseIsoDate(ph.date), lang)}</span>
            </button>
          ))
        )}
      </div>
      {large !== undefined && (
        <div className="ph-large" role="dialog" aria-modal="true" aria-label={label} onClick={() => setLargeId(null)}>
          <div className="ph-large-box" onClick={(e) => e.stopPropagation()}>
            <img src={large.screenUrl} alt={large.note ?? label} decoding="async" />
            <div className="ph-large-foot">
              <span className="m num">
                {longDate(parseIsoDate(large.date), lang)}
                {large.note ? ` · ${large.note}` : ''}
              </span>
              <span className="acts">
                <a
                  className="ibtn"
                  href={large.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={t('app.photo_original')}
                  title={t('app.photo_original')}
                >
                  <Icon name="image" />
                </a>
                <ConfirmButton
                  text
                  label={t('app.delete')}
                  onConfirm={() => {
                    onDelete(large.id)
                    setLargeId(null)
                  }}
                />
                <button type="button" className="ibtn" aria-label={t('app.close')} onClick={() => setLargeId(null)}>
                  <Icon name="x" />
                </button>
              </span>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
