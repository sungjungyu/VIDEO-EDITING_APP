export default function ProgressBar({ percent, height = 10 }) {
  return (
    <div className="bar" style={{ height }}>
      <i style={{ width: `${Math.min(percent, 100)}%` }} />
    </div>
  );
}
