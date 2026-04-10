import { useState, useEffect } from 'react';
import './BatchProcessor.css';

export default function BatchProcessor({ onRefresh }) {
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState(null);

  const fetchStatus = async () => {
    try {
      const res = await fetch('/api/contracts/status');
      const data = await res.json();
      setStatus(data);
      if (data.status === 'running') {
        setTimeout(fetchStatus, 2000);
      } else if (data.status === 'completed' || data.status === 'error') {
        if (loading) onRefresh();
        setLoading(false);
      }
    } catch (e) {
      console.error('Failed to fetch batch status');
    }
  };

  useEffect(() => {
    fetchStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleBatch = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/contracts/batch', { method: 'POST' });
      if (!res.ok) throw new Error('Batch conflict or error');
      window.toast('Batch processing started!', 'success');
      fetchStatus();
    } catch (e) {
      window.toast('Failed to start batch processing', 'error');
      setLoading(false);
    }
  };

  const isRunning = status?.status === 'running';
  const progressPercent = status?.total > 0 ? (status.processed / status.total) * 100 : 0;

  return (
    <div className="card batch-card">
      <div className="card-header">
        <div className="icon icon-green">⚡</div>
        <h2>Batch Processing</h2>
      </div>
      <div className="card-body">
        <p style={{ fontSize: '0.83rem', color: 'var(--text-muted)', marginBottom: '16px' }}>
          Process all contracts in the <code style={{ background: 'var(--surface2)', padding: '2px 6px', borderRadius: '4px', fontSize: '0.78rem' }}>/data/contracts/</code> directory with 5 parallel workers.
        </p>
        
        <button className="btn btn-success btn-full" disabled={isRunning} onClick={handleBatch}>
          {isRunning && <span className="spinner" style={{ marginRight: '8px' }}></span>}
          {isRunning ? 'Processing...' : '⚡ Process All Contracts'}
        </button>

        {isRunning && status && (
          <div className="progress-section">
            <div className="progress-label">
              <span>Progress</span>
              <span>{status.processed} / {status.total}</span>
            </div>
            <div className="progress-bar-wrap">
              <div className="progress-bar" style={{ width: `${progressPercent}%` }}></div>
            </div>
            <div className="progress-status">Processing...</div>
          </div>
        )}
      </div>
    </div>
  );
}
