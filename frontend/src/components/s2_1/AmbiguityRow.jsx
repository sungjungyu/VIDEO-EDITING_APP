import Chip from '../common/Chip.jsx';

export default function AmbiguityRow({ item, number, onChange }) {
  return (
    <div style={{ marginTop: 8 }}>
      <div>{number != null && `${number}. `}{item.message}</div>
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
