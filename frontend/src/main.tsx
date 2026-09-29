import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/geologica'
import '@fontsource-variable/golos-text'
import '@/styles/tokens.css'
import '@/styles/base.css'
import { App } from '@/app/App'

const root = document.getElementById('root')
if (root === null) throw new Error('#root is missing from index.html')

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
