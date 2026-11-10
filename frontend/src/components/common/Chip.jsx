/**
 * variant: 'default' | 'on' | 'done' | 'add'
 */
export default function Chip({ children, variant = 'default', onClick }) {
  const cls = ['chip', variant !== 'default' ? variant : ''].filter(Boolean).join(' ');
  return (
    <span className={cls} onClick={onClick} style={onClick ? { cursor: 'pointer' } : undefined}>
      {children}
    </span>
  );
}
