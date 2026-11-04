import { Component } from 'react';

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', height: '100vh', gap: 16, padding: 24,
        }}>
          <div style={{ fontSize: 32 }}>⚠️</div>
          <div style={{ fontWeight: 600, fontSize: 16 }}>화면을 표시하는 중 오류가 발생했어요</div>
          <pre style={{
            background: 'var(--color-surface-2, #f4f4f5)', borderRadius: 8,
            padding: '10px 14px', fontSize: 12, maxWidth: 560, overflowX: 'auto',
            color: 'var(--color-danger, #e53e3e)', whiteSpace: 'pre-wrap', wordBreak: 'break-all',
          }}>
            {this.state.error.message}
          </pre>
          <button
            className="btn-primary"
            onClick={() => {
              localStorage.clear();
              window.location.hash = '';
              window.location.reload();
            }}
          >
            처음으로
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
