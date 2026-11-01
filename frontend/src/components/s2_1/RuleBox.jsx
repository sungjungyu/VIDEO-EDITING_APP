import Badge from '../common/Badge.jsx';
import Chip from '../common/Chip.jsx';

export default function RuleBox({ title, badgeVariant, badgeLabel, items, onRemove, onAdd }) {
  return (
    <div className="box">
      <div className="sec">
        {title} <Badge variant={badgeVariant}>{badgeLabel}</Badge>
      </div>
      <div className="row">
        {items.map((item, i) => (
          <Chip key={i} variant="default">
            {item} <span style={{ cursor: 'pointer' }} onClick={() => onRemove?.(i)}>×</span>
          </Chip>
        ))}
        <Chip variant="add" onClick={onAdd}>+ 추가</Chip>
      </div>
    </div>
  );
}
