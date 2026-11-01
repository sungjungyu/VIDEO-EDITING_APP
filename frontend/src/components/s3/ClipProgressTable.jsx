import { useProject } from '../../state/ProjectContext.jsx';
import { fmtDuration } from '../../utils/format.js';

function StatusBar({ status, percent }) {
  if (status === 'done')
    return <div className="bar" style={{ height: 7 }}><i style={{ width: '100%', background: 'var(--color-success)' }} /></div>;
  if (status === 'running')
    return <div className="bar" style={{ height: 7 }}><i style={{ width: `${percent ?? 50}%` }} /></div>;
  if (status === 'failed')
    return <span style={{ color: 'var(--color-danger)' }}>실패</span>;
  return <span className="lb">대기</span>;
}

export default function ClipProgressTable({ clipProgress }) {
  const { clips } = useProject();

  return (
    <table>
      <thead>
        <tr>
          <th>#</th><th>클립</th><th>길이</th><th style={{ width: '26%' }}>받아쓰기</th><th style={{ width: '30%' }}>영상 분석</th>
        </tr>
      </thead>
      <tbody>
        {clips.map((clip, i) => {
          const prog = clipProgress?.find(p => p.id === clip.id);
          const name = clip.file.replace(/\.[^/.]+$/, '');
          return (
            <tr key={clip.id}>
              <td>{i + 1}</td>
              <td>{name}</td>
              <td>{fmtDuration(clip.duration)}</td>
              <td><StatusBar status={prog?.stt ?? 'waiting'} /></td>
              <td>
                <StatusBar status={prog?.vision ?? 'waiting'} percent={prog?.vision_percent} />
                {prog?.vision === 'failed' && (
                  <button style={{ height: 22, fontSize: 10, padding: '0 6px', marginLeft: 4 }}>다시 시도</button>
                )}
                {prog?.error && <div className="lb" style={{ marginTop: 2, color: 'var(--color-danger)' }}>{prog.error}</div>}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
