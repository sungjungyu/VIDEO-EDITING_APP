import Chip from '../common/Chip.jsx';

export default function AmbiguityRow({ item, onChange }) {
  return (
    <div style={{ marginTop: 6 }}>
      <div>{item.message}</div>
      <div className="row" style={{ marginTop: 4 }}>
        {item.options.map(opt => (
          <Chip
            key={opt}
            variant={item.chosen === opt ? 'on' : 'default'}
            onClick={() => onChange?.({ ...item, chosen: opt })}
          >
            {opt}
          </Chip>
        ))}
      </div>
    </div>
  );
}
