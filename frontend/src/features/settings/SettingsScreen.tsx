import { useState } from 'react'
import { api } from '@/api/client'
import { SectionTabs } from '@/components/controls/SectionTabs'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { Headline, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { ConnectionsSection } from './ConnectionsSection'
import { DataSection } from './DataSection'
import { GeneralSection } from './GeneralSection'
import { ProactiveSection } from './ProactiveSection'
import { SecuritySection } from './SecuritySection'
import { useSettingsView } from './useSettingsView'
import './settings.css'

export default function SettingsScreen() {
  const { t } = useT()
  const { data: settings } = useSettingsView()
  const [activeTab, setActiveTab] = useState<string>('main')

  const tabs = [
    { id: 'main', label: t('settings.tab.main') },
    { id: 'conn', label: t('settings.tab.conn') },
    { id: 'pro', label: t('settings.tab.pro') },
    { id: 'data', label: t('settings.tab.data') },
    { id: 'login', label: t('settings.tab.login') },
  ]

  const handleRestart = async () => {
    if (!window.confirm(t('settings.restart_confirm'))) {
      return
    }

    try {
      const res = await api.POST('/api/v1/settings/restart')
      if (res.data) {
        toast(t('settings.saved.restart'))
      }
    } catch (err: any) {
      toast(err.message || 'Error restarting container', { icon: 'warn' })
    }
  }

  return (
    <>
      <TopBar
        title={t('nav.settings')}
        right={
          <button
            type="button"
            className="ibtn"
            onClick={handleRestart}
            title={t('settings.restart_btn')}
            aria-label={t('settings.restart_btn')}
          >
            <Icon name="sync" />
          </button>
        }
      />

      <header className="mast">
        <div className="kicker">
          <span className="crumb">{t('app.system')}</span>
        </div>
        <div className="mast-actions">
          <button
            type="button"
            className="btn ghost flex items-center gap-2"
            onClick={handleRestart}
          >
            <Icon name="sync" />
            <span>{t('settings.restart_btn')}</span>
          </button>
        </div>
        <SectionTabs
          items={tabs}
          active={activeTab}
          onSelect={(id) => setActiveTab(id)}
          sub
        />
      </header>

      <Headline title={t('nav.settings')}>
        <p className="sub lede text-sm text-[var(--muted)] max-w-[70ch] mt-2 mb-4">
          {t('settings.description')}
        </p>
      </Headline>

      <div className="settings-content mt-4">
        {activeTab === 'main' && <GeneralSection settings={settings} />}
        {activeTab === 'conn' && <ConnectionsSection settings={settings} />}
        {activeTab === 'pro' && <ProactiveSection settings={settings} />}
        {activeTab === 'data' && <DataSection />}
        {activeTab === 'login' && <SecuritySection settings={settings} />}
      </div>
    </>
  )
}
