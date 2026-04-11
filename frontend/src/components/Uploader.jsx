import { useState, useRef } from 'react';
import './Uploader.css';

export default function Uploader({ onUploadSuccess, onViewJson, onViewRoleViews }) {
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef(null);

  const handleFileChange = (e) => setFile(e.target.files[0]);
  
  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const f = e.dataTransfer.files[0];
      setFile(f);
      if (fileInputRef.current) fileInputRef.current.files = e.dataTransfer.files;
    }
  };

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true);
    setResult(null);

    const fd = new FormData();
    fd.append('file', file);

    try {
      const res = await fetch('/api/contracts/upload', {
        method: 'POST',
        body: fd
      });
      const data = await res.json();
      if (!data.success) throw new Error(data.error);
      setResult(data.data);
      window.toast('Contract analyzed successfully!', 'success');
      onUploadSuccess();
    } catch (e) {
      window.toast(`Upload failed: ${e.message}`, 'error');
    } finally {
      setLoading(false);
    }
  };

  const field = (k, v) => (
    <div className="result-field"><span className="key">{k}</span><span className="val">{v}</span></div>
  );

  return (
    <div className="card uploader-card">
      <div className="card-header">
        <div className="icon icon-blue">📤</div>
        <h2>Upload & Analyze</h2>
      </div>
      <div className="card-body">
        <div 
          className={`upload-zone ${isDragOver ? 'drag-over' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
          onDragLeave={() => setIsDragOver(false)}
          onDrop={handleDrop}
        >
          <input type="file" ref={fileInputRef} onChange={handleFileChange} accept=".pdf" />
          <div className="upload-icon">📋</div>
          <h3>{file ? file.name : 'Drop a contract PDF here'}</h3>
          <p>or click to browse · Max 50MB</p>
        </div>

        <button className="btn btn-primary btn-full" disabled={!file || loading} onClick={handleUpload}>
          {loading && <span className="spinner" style={{ marginRight: '8px' }}></span>}
          {loading ? 'Analyzing...' : 'Analyze Contract'}
        </button>

        {result && (
          <div id="upload-result">
            <div className="result-preview" id="result-preview">
              <div className="contract-type-badge">{result.contract_type?.label || 'Other'}</div>
              {field('File', result.source_metadata?.file_name)}
              {field('Parties', (result.parties||[]).map(p => p.name).join(', ') || '—')}
              {field('Governing Law', result.clauses?.governing_law?.normalized_value?.state || result.clauses?.governing_law?.raw_text || '—')}
              {field('Payment Terms', result.structured_fields?.payment_terms?.raw_text || '—')}
              {field('Liability Cap', result.structured_fields?.liability_cap?.raw_text || '—')}
              {field('Notice Period', result.structured_fields?.notice_period?.raw_text || '—')}
              {field('Non-Compete', result.clauses?.non_compete?.status === 'present' ? '✅ Yes' : '❌ No')}
              {field('Audit Rights', result.clauses?.audit_rights?.status === 'present' ? '✅ Yes' : '❌ No')}
            </div>
            <div className="upload-result-actions">
              <button className="btn btn-secondary btn-full" type="button" onClick={() => onViewJson?.(result)}>
                View Full JSON
              </button>
              <button className="btn btn-secondary btn-full" type="button" onClick={() => onViewRoleViews?.(result)}>
                Role-based views
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
