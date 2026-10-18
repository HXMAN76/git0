import { createRoot } from 'react-dom/client'
import '../index.css'
import './ide.css'
import App from './App.tsx'

// No StrictMode: the session controller creates a backend session on mount, and a double mount would
// create (and leak) a second one.
createRoot(document.getElementById('root')!).render(<App />)
