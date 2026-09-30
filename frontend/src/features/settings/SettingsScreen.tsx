import { useState } from 'react'
import { SectionTabs } from '@/components/controls/SectionTabs'
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
  const settings = useSettingsView()
  const [activeTab, setActiveTab] = useState<string>('main')

  const tabs = [
    { id: 'main', label: t('settings.tab.main') },
    { id: 'conn', label: t('settings.tab.conn') },
    { id: 'pro', label: t('settings.tab.pro') },
    { id: 'data', label: t('settings.tab.data') },
    { id: 'login', label: t('settings.tab.login') },
  ]

  return (
    <>
      <TopBar title={t('nav.settings')} />

      <header className="mast">
        <div className="kicker">
          <span className="crumb">{t('app.system')}</span>
        </div>
        <SectionTabs
          items={tabs}
          active={activeTab}
          onSelect={(id) => setActiveTab(id)}
        />
      </header>

      <Headline title={t('nav.settings')}>
        <p className="sub lede settings-desc">
          {t('settings.description')}
        </p>
      </Headline>

      <div className="settings-content">
        {activeTab === 'main' && <GeneralSection settings={settings} />}
        {activeTab === 'conn' && <ConnectionsSection settings={settings} />}
        {activeTab === 'pro' && <ProactiveSection settings={settings} />}
        {activeTab === 'data' && <DataSection />}
        {activeTab === 'login' && <SecuritySection settings={settings} />}
      </div>
    </>
  )
}
