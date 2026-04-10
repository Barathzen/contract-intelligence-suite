import { useState, useMemo } from 'react';
import './ResultsTable.css';

const PAGE_SIZE = 20;

export default function ResultsTable({ results, onRefresh, onRowClick }) {
  const [activeType, setActiveType] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(1);

  const types = useMemo(() => {
    return ['all', ...new Set(results.map(r => r.contract_type?.label || 'Other'))].sort();
  }, [results]);

  const filteredResults = useMemo(() => {
    return results.filter(r => {
      const matchType = activeType === 'all' || r.contract_type?.label === activeType;
      const q = searchQuery.toLowerCase();
      const filename = r.source_metadata?.file_name || '';
      const govLaw = r.clauses?.governing_law?.raw_text || '';
      const parties = r.parties?.map(p => p.name).join(', ') || '';
      const matchSearch = !q || [
        filename, govLaw, r.contract_type?.label, parties
      ].some(v => v && v.toLowerCase().includes(q));
      return matchType && matchSearch;
    });
  }, [results, activeType, searchQuery]);

  const totalPages = Math.ceil(filteredResults.length / PAGE_SIZE);
  const startIdx = (currentPage - 1) * PAGE_SIZE;
  const currentData = filteredResults.slice(startIdx, startIdx + PAGE_SIZE);

  const getTypeClass = (t) => {
    const map = {
      'Service Agreement': 'service',
      'IP Agreement': 'ip',
      'Lease Agreement': 'lease',
      'Supply Agreement': 'supply',
      'Employment Agreement': 'employment',
      'Non-Disclosure Agreement': 'nda',
      'License Agreement': 'license',
    };
    return map[t] || 'other';
  };

  const handlePageChange = (page) => {
    setCurrentPage(page);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return (
    <div className="card">
      <div className="card-header">
        <div className="icon icon-purple">📊</div>
        <h2>Processed Contracts</h2>
        <button className="btn btn-secondary" style={{ marginLeft: 'auto', fontSize: '0.75rem', padding: '6px 12px' }} onClick={onRefresh}>
          ↻ Refresh
        </button>
      </div>
      <div className="card-body" style={{ paddingTop: '16px' }}>
        <div className="search-wrap">
          <span className="search-icon">🔍</span>
          <input 
            type="text" 
            placeholder="Search by filename, party, or governing law…" 
            value={searchQuery}
            onChange={(e) => { setSearchQuery(e.target.value); setCurrentPage(1); }}
          />
        </div>
        
        <div className="filter-row">
          {types.map(type => (
            <div 
              key={type}
              className={`filter-chip ${type === activeType ? 'active' : ''}`}
              onClick={() => { setActiveType(type); setCurrentPage(1); }}
            >
              {type === 'all' ? `All (${results.length})` : type}
            </div>
          ))}
        </div>

        <div className="results-table-wrap">
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Type</th>
                <th>Parties</th>
                <th>Gov. Law</th>
                <th>Non-Compete</th>
                <th>Pages</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {currentData.length === 0 ? (
                <tr>
                  <td colSpan="7">
                    <div className="empty-state">
                      <div className="icon">📭</div>
                      <p>No results yet. Upload a contract or run batch processing.</p>
                    </div>
                  </td>
                </tr>
              ) : (
                currentData.map((r, i) => {
                  const filename = r.source_metadata?.file_name;
                  const typeLabel = r.contract_type?.label || 'Other';
                  const partiesStr = r.parties?.map(p => p.name).slice(0,2).join(', ');
                  const govLaw = r.clauses?.governing_law?.normalized_value?.state || r.clauses?.governing_law?.raw_text || '—';
                  const nonCompete = r.clauses?.non_compete?.status === 'present';
                  const pageCount = r.source_metadata?.page_count || 0;
                  const timeSec = (r.processing_metadata?.processing_time_ms || 0) / 1000;
                  
                  return (
                    <tr key={i} onClick={() => onRowClick(r)}>
                      <td className="file-col" title={filename}>{filename}</td>
                      <td><span className={`type-pill type-${getTypeClass(typeLabel)}`}>{typeLabel}</span></td>
                      <td className="parties-col" title={r.parties?.map(p => p.name).join(', ')}>{partiesStr}</td>
                      <td style={{ color: 'var(--text-dim)' }}>{govLaw}</td>
                      <td>
                        <span className={`bool-dot ${nonCompete ? 'yes' : 'no'}`}></span>
                        {nonCompete ? 'Yes' : 'No'}
                      </td>
                      <td style={{ color: 'var(--text-muted)' }}>{pageCount}</td>
                      <td style={{ color: 'var(--text-muted)' }}>{timeSec}s</td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>

        {totalPages > 1 && (
          <div className="pagination">
            <span className="page-info">{filteredResults.length} results</span>
            {currentPage > 1 && <div className="page-btn" onClick={() => handlePageChange(currentPage - 1)}>‹</div>}
            
            {Array.from({ length: totalPages }, (_, i) => i + 1).map(p => {
              // Simple window logic (show nearby pages)
              if (p >= currentPage - 2 && p <= currentPage + 2) {
                return (
                  <div key={p} className={`page-btn ${p === currentPage ? 'active' : ''}`} onClick={() => handlePageChange(p)}>
                    {p}
                  </div>
                );
              }
              return null;
            })}

            {currentPage < totalPages && <div className="page-btn" onClick={() => handlePageChange(currentPage + 1)}>›</div>}
          </div>
        )}
      </div>
    </div>
  );
}
