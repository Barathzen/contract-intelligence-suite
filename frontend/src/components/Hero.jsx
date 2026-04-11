import './Hero.css';

export default function Hero({ stats }) {
  return (
    <>
      <div className="hero">
        <h1>Transform Legal Contracts<br/><span className="gradient">Into Structured Intelligence</span></h1>
        <p>Upload PDFs, extract clauses, identify parties, governing law, liability caps — all in seconds.</p>
      </div>

      <div className="stats-row">
        <div className="stat-card">
          <div className="stat-value blue">{stats.available}</div>
          <div className="stat-label">Contracts Available</div>
        </div>
        <div className="stat-card">
          <div className="stat-value green">{stats.processed}</div>
          <div className="stat-label">Processed</div>
        </div>
        <div className="stat-card">
          <div className="stat-value purple">{stats.types}</div>
          <div className="stat-label">Contract Types</div>
        </div>
        <div
          className="stat-card"
          title="Mean of overall_confidence across saved results (model-reported, not legal accuracy)."
        >
          <div className="stat-value yellow">{stats.avgConfidence}</div>
          <div className="stat-label">Avg. confidence</div>
        </div>
      </div>
    </>
  );
}
