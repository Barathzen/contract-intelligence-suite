import { useState, useEffect } from 'react';
import Hero from './components/Hero.jsx';
import Uploader from './components/Uploader.jsx';
import BatchProcessor from './components/BatchProcessor.jsx';
import ResultsTable from './components/ResultsTable.jsx';
import ContractDetailModal from './components/ContractDetailModal.jsx';
import JSONModal from './components/JSONModal.jsx';
import './App.css';

// Toast system
window.toast = (msg, type = 'info') => {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.innerHTML = `<span>${type === 'success' ? '✅' : type === 'error' ? '❌' : 'ℹ️'}</span><span>${msg}</span>`;
  container.appendChild(t);
  setTimeout(() => t.remove(), 4000);
};

export default function App() {
  const [stats, setStats] = useState({
    available: '—',
    processed: '—',
    types: '—',
    avgConfidence: '—',
  });
  const [results, setResults] = useState([]);
  const [selectedContract, setSelectedContract] = useState(null);
  const [jsonModal, setJsonModal] = useState(null);

  const fetchHealth = async () => {
    try {
      const res = await fetch('/api/contracts/health');
      const data = await res.json();
      setStats((prev) => ({
        ...prev,
        available: data.contracts_available ?? '—',
        processed: data.contracts_processed ?? '—',
      }));
    } catch (e) {
      console.error(e);
    }
  };

  const fetchResults = async () => {
    try {
      const res = await fetch('/api/contracts/results');
      if (!res.ok) throw new Error();
      const data = await res.json();
      const resList = data.results || [];
      setResults(resList);

      const types = new Set(resList.map(r => r.contract_type?.label || 'Other'));
      const withConf = resList.filter(
        (r) => typeof r.confidence_summary?.overall_confidence === 'number'
      );
      const avgConfidence =
        withConf.length > 0
          ? `${Math.round(
              (withConf.reduce((s, r) => s + r.confidence_summary.overall_confidence, 0) /
                withConf.length) *
                100
            )}%`
          : '—';

      setStats((prev) => ({
        ...prev,
        types: types.size || '—',
        processed: resList.length,
        avgConfidence,
      }));
    } catch (e) {
      window.toast('Failed to load results', 'error');
    }
  };

  useEffect(() => {
    // Inject toast container
    const c = document.createElement('div');
    c.id = 'toast-container';
    document.body.appendChild(c);
    
    fetchHealth();
    fetchResults();

    return () => c.remove();
  }, []);

  return (
    <div className="app">
      <nav className="navbar">
        <div className="nav-brand">
          <div className="nav-logo">⚖️</div>
          <span className="nav-title">Contract <span>Intelligence</span></span>
          <span className="nav-badge">AI</span>
        </div>
        <div className="nav-links">
          <a href="/api/docs" target="_blank" rel="noreferrer">API Docs</a>
          <a href="#results-section">Results</a>
        </div>
      </nav>

      <Hero stats={stats} />

      <div className="main-grid">
        <div className="left-panel">
          <Uploader
            onUploadSuccess={() => { fetchResults(); fetchHealth(); }}
            onViewJson={(data) =>
              setJsonModal({
                data,
                contractFile: data?.source_metadata?.file_name || 'Contract',
              })
            }
            onViewRoleViews={setSelectedContract}
          />
          <BatchProcessor onRefresh={() => { fetchResults(); fetchHealth(); }} />
        </div>
        <div className="right-panel" id="results-section">
          <ResultsTable results={results} onRefresh={() => { fetchResults(); fetchHealth(); }} onRowClick={setSelectedContract} />
        </div>
      </div>

      {selectedContract && (
        <ContractDetailModal
          data={selectedContract}
          onClose={() => setSelectedContract(null)}
        />
      )}
      {jsonModal && (
        <JSONModal
          contractFile={jsonModal.contractFile}
          data={jsonModal.data}
          onClose={() => setJsonModal(null)}
        />
      )}
    </div>
  );
}
