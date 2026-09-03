import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import App from './App';
import './styles/tokens.css';
import './styles.css';
import './styles/shell.css';
import './styles/user.css';
import './styles/user-data.css';
import './styles/enterprise.css';
import './styles/enterprise-search-analytics.css';
import './styles/enterprise-feedback-analytics.css';
import './styles/admin.css';
import './styles/shared.css';
import './styles/jobs.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
