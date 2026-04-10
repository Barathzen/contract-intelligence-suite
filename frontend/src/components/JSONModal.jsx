import { useEffect, useRef } from 'react';
import './JSONModal.css';

const colorizeJson = (obj) => {
  const json = JSON.stringify(obj, null, 2);
  return json
    .replace(/("[\w_]+")\s*:/g, '<span class="json-key">$1</span>:')
    .replace(/:\s*(".*?")/g, (_, s) => `: <span class="json-str">${s}</span>`)
    .replace(/:\s*(true)/g, ': <span class="json-bool-true">true</span>')
    .replace(/:\s*(false)/g, ': <span class="json-bool-false">false</span>')
    .replace(/:\s*(null)/g, ': <span class="json-null">null</span>')
    .replace(/:\s*(\d+(?:\.\d+)?)/g, ': <span class="json-num">$1</span>');
};

export default function JSONModal({ contractFile, data, onClose }) {
  const overlayRef = useRef(null);

  useEffect(() => {
    const handleEsc = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [onClose]);

  const handleOverlayClick = (e) => {
    if (e.target === overlayRef.current) onClose();
  };

  return (
    <div className="modal-overlay open" ref={overlayRef} onClick={handleOverlayClick}>
      <div className="modal">
        <div className="modal-header">
          <h3>{contractFile}</h3>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <div 
            className="json-viewer" 
            dangerouslySetInnerHTML={{ __html: colorizeJson(data) }} 
          />
        </div>
      </div>
    </div>
  );
}
