import { useState, useEffect } from 'react';
import { updateDashboard, getDashboard } from '../../lib/dashboards';
import './ShareDropdownPanel.css';

interface ShareDropdownPanelProps {
  dashboardId: string;
}

export function ShareDropdownPanel({ dashboardId }: ShareDropdownPanelProps) {
  const [isPublic, setIsPublic] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);

  const shareUrl = `${window.location.origin}/shared/${dashboardId}`;

  useEffect(() => {
    let mounted = true;
    getDashboard(dashboardId).then((dash) => {
      if (mounted) {
        setIsPublic(dash.is_public);
        setLoading(false);
      }
    }).catch(console.error);
    return () => { mounted = false; };
  }, [dashboardId]);

  const handleToggle = async () => {
    setSaving(true);
    try {
      const updated = await updateDashboard(dashboardId, undefined, undefined, !isPublic);
      setIsPublic(updated.is_public);
    } catch (err) {
      console.error('Failed to update share settings:', err);
    } finally {
      setSaving(false);
    }
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="share-dropdown-panel" onClick={(e) => e.stopPropagation()}>
      <div className="share-dropdown-header">
        <strong>Share Dashboard</strong>
        <p className="share-dropdown-subtitle">Anyone with the link can view.</p>
      </div>
      
      <div className="share-dropdown-body">
        {loading ? (
          <div className="loading-spinner" style={{ margin: '1rem auto' }}></div>
        ) : (
          <>
            <label className="toggle-label">
              <span className="toggle-text">Public access</span>
              <input 
                type="checkbox" 
                className="toggle-switch" 
                checked={isPublic} 
                onChange={handleToggle}
                disabled={saving}
                aria-label="Toggle public access"
              />
            </label>
            
            {isPublic && (
              <div className="share-link-container">
                <input 
                  type="text" 
                  readOnly 
                  value={shareUrl} 
                  className="share-link-input"
                  onClick={(e) => e.currentTarget.select()}
                  aria-label="Public share link"
                />
                <button 
                  className="primary-btn copy-btn" 
                  onClick={handleCopy}
                >
                  {copied ? 'Copied!' : 'Copy Link'}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
