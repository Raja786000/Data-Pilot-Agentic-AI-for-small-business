import React from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource/atkinson-hyperlegible/400.css';
import '@fontsource/atkinson-hyperlegible/700.css';
import '@fontsource/fraunces/600.css';
import '@fontsource/fraunces/700.css';
import './styles.css';
import App from './App.jsx';
import { ErrorBoundary } from './ui.jsx';

createRoot(document.getElementById('root')).render(
  <ErrorBoundary full><App /></ErrorBoundary>
);
