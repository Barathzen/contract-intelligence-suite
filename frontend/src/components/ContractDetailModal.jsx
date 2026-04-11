import { useState, useEffect, useCallback, useMemo } from 'react';
import './ContractDetailModal.css';

const ROLES = [
  { key: 'legal',      icon: '⚖️',  label: 'Legal' },
  { key: 'business',   icon: '🧑‍💼', label: 'Business' },
  { key: 'compliance', icon: '🛡️',  label: 'Compliance' },
  { key: 'executive',  icon: '💼',  label: 'Executive' },
];

/** Matches backend: output file is `{stem}.json`; stem is basename without .pdf (any case). */
function resolveIntelligenceLookupKeys(payload) {
  if (!payload) return [];
  const keys = [];
  const seen = new Set();
  const push = (k) => {
    if (k && !seen.has(k)) {
      seen.add(k);
      keys.push(k);
    }
  };
  const meta = payload.source_metadata || payload.sourceMetadata;
  const fn = meta?.file_name ?? meta?.fileName;
  if (fn) {
    const base = fn.split(/[/\\]/).pop() || fn;
    push(base.replace(/\.pdf$/i, ''));
  }
  push(payload.contract_id ?? payload.contractId);
  return keys;
}

function StatusBadge({ status }) {
  const cls = `status-badge status-${status}`;
  const icons = { present: '✓', uncertain: '~', not_found: '?' };
  return <span className={cls}>{icons[status] || '?'} {status?.replace('_', ' ')}</span>;
}

function RiskMeter({ score, level }) {
  const color = level === 'high' ? '#ef4444' : level === 'medium' ? '#f59e0b' : '#10b981';
  return (
    <div className="risk-score-wrap">
      <div className={`risk-score-num risk-${level}`}>{score}</div>
      <div className="risk-bar-wrap">
        <div className="risk-bar-bg">
          <div className="risk-bar-fill" style={{ width: `${score}%`, background: color }} />
        </div>
        <div className="risk-label">Risk Level: <strong style={{ color }}>{level?.toUpperCase()}</strong> — {score}/100</div>
      </div>
    </div>
  );
}

function ConfBar({ value }) {
  const pct = Math.round((value || 0) * 100);
  return (
    <div className="conf-bar-wrap">
      <div className="conf-bar-bg">
        <div className="conf-bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="conf-pct">{pct}%</span>
    </div>
  );
}

// ── Legal View ─────────────────────────────────────────────
function LegalView({ data }) {
  const all = [...(data.clauses_found || []), ...(data.clauses_uncertain || []), ...(data.clauses_missing || [])];
  return (
    <>
      <div className="view-section">
        <div className="view-section-header">Parties</div>
        <div className="info-grid">
          {(data.parties || []).map((p, i) => (
            <div key={i} className="info-cell">
              <div className="label">{p.role || 'Unspecified'}</div>
              <div className="value">{p.name}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="view-section">
        <div className="view-section-header">Clause Analysis — {data.clauses_found?.length} found · {data.clauses_uncertain?.length} uncertain · {data.clauses_missing?.length} not found</div>
        <div className="clause-list">
          {all.map((c, i) => (
            <div key={i} className="clause-item">
              <div style={{ minWidth: 140 }}>
                <div className="clause-name">{c.clause}</div>
                <StatusBadge status={c.status} />
              </div>
              <div style={{ flex: 1 }}>
                {c.raw_text
                  ? <div className="clause-text">{c.raw_text}</div>
                  : <div className="clause-text" style={{ fontStyle: 'italic' }}>No text extracted</div>
                }
                <ConfBar value={c.confidence} />
              </div>
              <div className="clause-conf">
                <span className={`status-badge status-${c.risk_level === 'high' ? 'not_found' : c.risk_level === 'medium' ? 'uncertain' : 'present'}`}>
                  {c.risk_level} risk
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {(data.risk_flags || []).length > 0 && (
        <div className="view-section">
          <div className="view-section-header">Risk Flags</div>
          <ul className="issues-list">
            {data.risk_flags.map((f, i) => <li key={i}>{f}</li>)}
          </ul>
        </div>
      )}
    </>
  );
}

// ── Business View ─────────────────────────────────────────────
function BusinessView({ data }) {
  const fields = [
    { label: 'Payment Terms',  data: data.payment_terms },
    { label: 'Notice Period',  data: data.notice_period },
    { label: 'Liability Cap',  data: data.liability_cap },
    { label: 'Jurisdiction',   data: data.jurisdiction },
  ];
  return (
    <>
      <div className="view-section">
        <div className="view-section-header">Contract Overview</div>
        <div className="info-grid">
          <div className="info-cell"><div className="label">Type</div><div className="value">{data.contract_type || '—'}</div></div>
          <div className="info-cell"><div className="label">Pages</div><div className="value">{data.contract_duration_pages || '—'}</div></div>
          {(data.parties || []).map((p, i) => (
            <div key={i} className="info-cell">
              <div className="label">{p.role || 'Party'}</div>
              <div className="value">{p.name}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="view-section">
        <div className="view-section-header">Commercial Terms</div>
        <div className="clause-list">
          {fields.map(({ label, data: f }, i) => (
            <div key={i} className="clause-item">
              <div style={{ minWidth: 140 }}>
                <div className="clause-name">{label}</div>
                <StatusBadge status={f?.status || 'not_found'} />
              </div>
              <div style={{ flex: 1 }}>
                {f?.raw_text
                  ? <div className="clause-text">{f.raw_text}</div>
                  : <div className="clause-text" style={{ fontStyle: 'italic' }}>Not specified in contract</div>
                }
                {f?.normalized_value && (
                  <div style={{ fontSize: '0.73rem', color: 'var(--accent)', marginTop: 4 }}>
                    {JSON.stringify(f.normalized_value)}
                  </div>
                )}
                <ConfBar value={f?.confidence} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {(data.key_obligations || []).length > 0 && (
        <div className="view-section">
          <div className="view-section-header">Key Obligations Found</div>
          <ul className="issues-list">
            {data.key_obligations.map((o, i) => (
              <li key={i}><span>{o.obligation}:</span>&nbsp;{o.text?.slice(0, 120)}…</li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

// ── Compliance View ─────────────────────────────────────────────
function ComplianceView({ data }) {
  return (
    <>
      <div className="view-section">
        <div className="view-section-header">Risk Assessment</div>
        <RiskMeter score={data.risk_score || 0} level={data.risk_level || 'low'} />
      </div>

      <div className="view-section">
        <div className="view-section-header">Missing Safeguards ({data.missing_safeguards?.length || 0})</div>
        {(data.missing_safeguards || []).length === 0
          ? <div className="view-empty">No missing safeguards detected.</div>
          : <div className="clause-list">
              {data.missing_safeguards.map((s, i) => (
                <div key={i} className="clause-item">
                  <div style={{ minWidth: 140 }}>
                    <div className="clause-name">{s.item}</div>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>{s.type}</span>
                  </div>
                  <StatusBadge status="not_found" />
                  <span className={`status-badge status-${s.risk_level === 'high' ? 'not_found' : s.risk_level === 'medium' ? 'uncertain' : 'present'}`} style={{ marginLeft: 'auto' }}>
                    {s.risk_level} risk
                  </span>
                </div>
              ))}
            </div>
        }
      </div>

      {(data.uncertain_items || []).length > 0 && (
        <div className="view-section">
          <div className="view-section-header">Uncertain Items ({data.uncertain_items.length})</div>
          <div className="clause-list">
            {data.uncertain_items.map((s, i) => (
              <div key={i} className="clause-item">
                <div style={{ minWidth: 140 }}>
                  <div className="clause-name">{s.item}</div>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>{s.type}</span>
                </div>
                <StatusBadge status="uncertain" />
                <ConfBar value={s.confidence} />
              </div>
            ))}
          </div>
        </div>
      )}

      {(data.compliance_issues || []).length > 0 && (
        <div className="view-section">
          <div className="view-section-header">Compliance Issues</div>
          <ul className="issues-list">
            {data.compliance_issues.map((iss, i) => <li key={i}>{iss}</li>)}
          </ul>
        </div>
      )}
    </>
  );
}

// ── Executive View ─────────────────────────────────────────────
function ExecutiveView({ data }) {
  const riskColor = data.risk_level === 'high' ? '#ef4444' : data.risk_level === 'medium' ? '#f59e0b' : '#10b981';
  return (
    <>
      <div className="view-section">
        <div className="view-section-header">Executive Summary</div>
        <div className="info-grid">
          <div className="info-cell"><div className="label">Contract Type</div><div className="value">{data.contract_type || '—'}</div></div>
          <div className="info-cell"><div className="label">Parties</div><div className="value">{data.parties_count || 0} identified</div></div>
          <div className="info-cell"><div className="label">Pages</div><div className="value">{data.page_count || '—'}</div></div>
          <div className="info-cell"><div className="label">Processing Time</div><div className="value">{data.processing_time_sec}s</div></div>
          <div className="info-cell"><div className="label">Clauses Found</div><div className="value">{data.clauses_found}</div></div>
          <div className="info-cell"><div className="label">Fields Extracted</div><div className="value">{data.fields_extracted}</div></div>
          <div className="info-cell"><div className="label">Confidence</div><div className="value">{Math.round((data.overall_confidence || 0) * 100)}%</div></div>
          <div className="info-cell"><div className="label">Governing Law</div><div className="value" style={{ fontSize: '0.78rem' }}>{data.governing_law}</div></div>
        </div>
      </div>

      <div className="view-section">
        <div className="view-section-header">Risk Score</div>
        <RiskMeter score={data.risk_score || 0} level={data.risk_level || 'low'} />
      </div>

      {(data.key_issues || []).length > 0 && (
        <div className="view-section">
          <div className="view-section-header">Top Issues (Action Required)</div>
          <ul className="issues-list">
            {data.key_issues.map((iss, i) => <li key={i}>{iss}</li>)}
          </ul>
        </div>
      )}

      <div className="view-section">
        <div className="view-section-header">Parties Involved</div>
        <div className="info-grid">
          {(data.parties || []).map((name, i) => (
            <div key={i} className="info-cell"><div className="label">Party {i + 1}</div><div className="value">{name}</div></div>
          ))}
        </div>
      </div>
    </>
  );
}

// ── Main Component ─────────────────────────────────────────────
export default function ContractDetailModal({ data, onClose }) {
  const [activeRole, setActiveRole] = useState('executive');
  const [viewData, setViewData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const lookupKeys = useMemo(() => resolveIntelligenceLookupKeys(data), [data]);

  const fetchView = useCallback(
    async (role) => {
      if (lookupKeys.length === 0) {
        setViewData(null);
        setError('Missing file name or contract id — cannot load role views.');
        setLoading(false);
        return;
      }
      setLoading(true);
      setError(null);
      setViewData(null);
      try {
        let lastStatus = 404;
        for (const key of lookupKeys) {
          const res = await fetch(
            `/api/intelligence/${role}-view/${encodeURIComponent(key)}`
          );
          if (res.ok) {
            setViewData(await res.json());
            return;
          }
          lastStatus = res.status;
          if (res.status !== 404) {
            const t = await res.text();
            throw new Error(
              `HTTP ${res.status}${t ? `: ${t.slice(0, 200)}` : ''}`
            );
          }
        }
        throw new Error(
          lastStatus === 404
            ? 'Contract not found on server. Ensure the backend saved output JSON and OUTPUT_DIR matches for /api/contracts and /api/intelligence.'
            : `HTTP ${lastStatus}`
        );
      } catch (e) {
        setError(e.message || 'Request failed');
        setViewData(null);
      } finally {
        setLoading(false);
      }
    },
    [lookupKeys]
  );

  useEffect(() => {
    fetchView(activeRole);
  }, [activeRole, fetchView]);

  // Close on Escape
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const contractType = data?.contract_type?.label || 'Contract';
  const fileName = data?.source_metadata?.file_name || 'Unknown';

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal-box">
        {/* Header */}
        <div className="modal-header">
          <div style={{ fontSize: '1.2rem' }}>📄</div>
          <h2>{fileName} <span style={{ color: 'var(--text-muted)', fontWeight: 400, fontSize: '0.85rem' }}>· {contractType}</span></h2>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>

        {/* Role Tabs */}
        <div className="role-tabs">
          {ROLES.map(r => (
            <div
              key={r.key}
              className={`role-tab ${activeRole === r.key ? 'active' : ''}`}
              onClick={() => setActiveRole(r.key)}
            >
              <span className="tab-icon">{r.icon}</span>
              {r.label} View
            </div>
          ))}
        </div>

        {/* Body */}
        <div className="modal-body">
          {loading && (
            <div className="view-loading">
              <div className="spinner" />
              <span>Loading {activeRole} view…</span>
            </div>
          )}
          {!loading && error && (
            <div className="view-empty" style={{ color: '#ef4444' }}>
              Failed to load view: {error}
            </div>
          )}
          {!loading && !error && viewData && (
            <>
              {activeRole === 'legal'      && <LegalView      data={viewData} />}
              {activeRole === 'business'   && <BusinessView   data={viewData} />}
              {activeRole === 'compliance' && <ComplianceView data={viewData} />}
              {activeRole === 'executive'  && <ExecutiveView  data={viewData} />}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
