import { useState } from 'react'
import { DomainAlerts } from '@/components/controls/DomainAlerts'
import { Segmented } from '@/components/controls/Segmented'
import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { formatPercent } from '@/lib/format'
import { DiaryPane } from './DiaryPane'
import { PhotosPane } from './PhotosPane'
import { adherence, dayProgress } from './plan'
import { type Editing, ProductsPane } from './ProductsPane'
import { RulesPane } from './RulesPane'
import { TodayChecklist } from './TodayChecklist'
import { useSkincareView } from './useSkincareView'
import './skincare.css'

type Pane = 'diary' | 'photos' | 'products' | 'rules'
const PANES: readonly Pane[] = ['diary', 'photos', 'products', 'rules']

/** Skincare: today's routine to tick off first, then the diary, the photos, the catalog and the
 *  rules — one at a time, instead of all of them stacked on one page. */
export default function SkincareScreen() {
  const { t, lang } = useT()
  const view = useSkincareView()
  const [pane, setPane] = useState<Pane>('diary')
  const [editing, setEditing] = useState<Editing>(null)

  const today = dayProgress(view.plan)
  const week = adherence(view.history, view.today)

  const addProduct = () => {
    setPane('products')
    setEditing('new')
  }

  return (
    <>
      <TopBar
        title={t('nav.skincare')}
        right={
          <button type="button" className="ibtn" onClick={addProduct} aria-label={t('app.skincare.add_product')}>
            <Icon name="plus" />
          </button>
        }
      />
      <Mast
        screen="skincare"
        actions={
          <button type="button" className="ghost" onClick={addProduct}>
            <Icon name="plus" />
            <span>{t('app.skincare.add_product')}</span>
          </button>
        }
      />
      <Headline title={t('nav.skincare')}>
        <div className="figs inline">
          <div className="f">
            <div className="f-v num">{today.total === 0 ? '—' : t('app.skincare.progress', { done: today.done, total: today.total })}</div>
            <div className="f-l">{t('app.skincare.today_done')}</div>
          </div>
          <div className="f">
            <div className="f-v num">{week === null ? '—' : formatPercent(week, lang)}</div>
            <div className="f-l">{t('app.skincare.adherence')}</div>
          </div>
        </div>
      </Headline>
      <DomainAlerts domain="skincare" />

      <TodayChecklist plan={view.plan} today={view.today} />

      <section className="sec sk-panes">
        <Segmented
          value={pane}
          onChange={setPane}
          label={t('nav.skincare')}
          options={PANES.map((id) => ({ id, label: t(`app.skincare.tab.${id}`) }))}
        />
      </section>
      {pane === 'diary' && <DiaryPane view={view} />}
      {pane === 'photos' && <PhotosPane view={view} />}
      {pane === 'products' && <ProductsPane view={view} editing={editing} setEditing={setEditing} />}
      {pane === 'rules' && <RulesPane view={view} />}
    </>
  )
}
